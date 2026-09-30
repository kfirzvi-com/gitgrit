"""Code-found candidates for links the topology inference tends to miss.

The LLM reads manifests and READMEs; the wiring between components usually
lives elsewhere — an ``AUTH_SERVICE_URL`` in a config file, a ``depends_on``
in docker-compose, an image pulled from another repository's registry, an SDK
import. This module finds those places deterministically and turns each into
a ``LinkCandidate``: where it was found, the token as written, and a short
roster shortlist of what it may point at. A model (Jev) later judges each
candidate; nothing here decides, and no text is generated.

Pure domain code: it works on a file list and a ``read_file`` callable and
must not import infrastructure.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import yaml

from app.domain.architecture.naming import canonical_key
from app.domain.architecture.paths import in_dirs, is_noise
from app.domain.architecture.resolve import INFRA_TERMS, RosterEntry, resolve_ref
from app.domain.architecture.topology import ComponentDecl, RepositoryTopology, clean_path

# Most specific evidence first: this is also the order candidates are emitted
# in, so the per-repo cap trims URLs before it trims compose edges.
REFERENCE_KINDS = ("compose_depends_on", "image", "k8s_ref", "env_var", "url", "sdk_client", "queue_name")

DEFAULT_LIMIT = 150  # candidates per repository; the JEV_MAP_MAX_CANDIDATES default too
MAX_OPTIONS = 6
MAX_FILES_PER_COMPONENT = 400
MAX_FILE_CHARS = 200_000
SNIPPET_RADIUS = 6
SNIPPET_CHARS = 1500
# YAML aliases make DAGs and cycles; a generated manifest can nest absurdly.
MAX_YAML_DEPTH = 50

# Top-level folders that belong to nobody's runtime: a root component owns the
# repository's own source, not its graveyard, docs or CI.
ROOT_ONLY_SKIP_DIRS = frozenset({
    "legacy", "deprecated", "archive", "archived", "docs", "doc", "examples",
    "samples", "tools", "scripts", "infra", "terraform", ".github", ".gitlab", ".circleci",
})
# Recorded test data: hundreds of JSON blobs that never wire anything.
DATA_DIRS = frozenset({"fixtures", "testdata", "__snapshots__", "snapshots"})
LOCK_FILES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock",
    "composer.lock", "cargo.lock", "go.sum", "uv.lock",
})
CONFIG_SUFFIXES = (".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties")
SOURCE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".go", ".java", ".rb", ".cs", ".php")
# Dependency manifests: scanned for SDK names on every line, not only imports.
MANIFEST_BASENAMES = frozenset({
    "package.json", "pyproject.toml", "requirements.txt", "go.mod", "gemfile", "composer.json", "pipfile",
})
DEPLOY_DIRS = frozenset({"deploy", "k8s", "kubernetes", "helm", "charts", "manifests"})
K8S_WORKLOAD_KINDS = frozenset({"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "ConfigMap"})

# Words that never identify a target on their own.
GENERIC_WORDS = frozenset({
    "url", "uri", "host", "hostname", "service", "svc", "api", "endpoint", "base", "public",
    "next", "addr", "address", "port", "dsn", "domain", "queue", "topic", "bucket", "name",
    "key", "secret", "token", "http", "https", "www", "com", "io", "dev", "net", "org",
    "prod", "production", "staging", "test", "local", "internal", "external", "cluster",
    "default", "latest", "env", "app", "server", "client", "backend", "frontend", "env",
    "vite", "react", "grpc", "rest",
})
# Used only when nothing specific matched: "API_URL" in a workspace with one api-gateway.
WEAK_WORDS = frozenset({"api"})
# INFRA_TERMS matched word by word (``infra_kind`` is a substring test and would
# drop "orders-service" because it contains "rds"), plus the plain words.
INFRA_WORDS = frozenset(INFRA_TERMS) | {"database", "db", "cache", "elasticache", "broker", "amqp"}
NON_SERVICE_HOSTS = frozenset({
    "github.com", "www.github.com", "gitlab.com", "bitbucket.org", "registry.npmjs.org",
    "npmjs.com", "www.npmjs.com", "pypi.org", "golang.org", "pkg.go.dev", "proxy.golang.org",
    "w3.org", "www.w3.org", "schema.org", "json-schema.org", "json.schemastore.org",
    "example.com", "www.example.com", "opensource.org", "creativecommons.org",
})
NON_SERVICE_HOST_PREFIXES = ("docs.", "schemas.", "xmlns.", "wiki.")
INTERNAL_HOST_SUFFIXES = (".svc.cluster.local", ".svc", ".local", ".internal", ".localhost", ".test", ".lan")
SECOND_LEVEL_TLDS = frozenset({"co", "com", "org", "net", "gov", "edu", "ac"})
SDK_NAMES = frozenset({
    "stripe", "twilio", "sendgrid", "mailgun", "postmark", "paypal", "braintree", "adyen",
    "plaid", "auth0", "okta", "firebase", "supabase", "algolia", "openai", "anthropic",
    "segment", "mixpanel", "amplitude", "launchdarkly", "datadog", "newrelic", "sentry",
    "pusher", "ably", "shopify", "hubspot", "salesforce", "zendesk", "intercom", "mapbox",
    "cloudinary", "contentful", "slack",
})

TOKEN_SPLIT_RE = re.compile(r"[_\-/.:@\s]+")
COMPOSE_FILE_RE = re.compile(r"^(?:docker-)?compose[\w.-]*\.ya?ml$")
ENV_VAR_RE = re.compile(
    r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:URL|URI|HOST|HOSTNAME|ENDPOINT|QUEUE|TOPIC|BUCKET|DSN|SERVICE|DOMAIN|ADDR))\b"
)
URL_RE = re.compile(r"https?://([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?::\d+)?(/[^\s'\"`)\]}>,;]*)?")
# A value's first bare token, bounded so one match never reads a whole huge line
# (a URL is ≤ 2048 chars; a longer token is not one).
_VALUE_TOKEN = r"[\"']?([^\s\"'#,;]{1,2048})"
# Matched with ``match(line, pos)`` right after the variable name: no ``^``, no slicing.
ASSIGNED_VALUE_RE = re.compile(r"\s*[=:]\s*" + _VALUE_TOKEN)
# The same token out of a value already parsed from YAML.
VALUE_TOKEN_RE = re.compile(r"\s*" + _VALUE_TOKEN)
# Snippet hygiene: the value of a credential-looking key, and userinfo in URLs.
_CREDENTIAL_KEY = r"""["']?[\w.-]*(?:SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|CREDENTIAL)[\w.-]*["']?"""
# ``KEY=value`` / ``KEY: value``, also as a compose list item (``- KEY=value``).
SECRET_LINE_RE = re.compile(r"^(\s*(?:-\s+)?(?:export\s+)?" + _CREDENTIAL_KEY + r"\s*[=:]\s*)(.*)$", re.I)
# The k8s env form: a ``value:`` line right after ``- name: <credential>``.
K8S_SECRET_NAME_RE = re.compile(r"^\s*(?:-\s+)?name:\s*" + _CREDENTIAL_KEY + r"\s*$", re.I)
K8S_VALUE_LINE_RE = re.compile(r"^(\s*value:\s*)(.*)$")
# A value that only points at a secret: a bare env-var name, ``os.environ…``,
# ``process.env…``, ``${…}`` / ``$…``. Not masked — there is nothing to leak.
SECRET_REFERENCE_RE = re.compile(r"^(?:[A-Z][A-Z0-9_]*$|os\.environ|process\.env|\$)")
URL_USERINFO_RE = re.compile(r"(://)[^\s/@'\"]+:[^\s/@'\"]+@")
BARE_HOST_RE = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::\d+)?$")
SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
QUEUE_KEY_RE = re.compile(
    r"""^\s*["']?([\w.-]*(?:queue|topic)(?:_?name|_?url)?)["']?\s*[:=]\s*["']?([A-Za-z][\w./:-]{2,})""", re.I
)
QUEUE_CALL_RE = re.compile(
    r"\b(?:publish|send_message|sendmessage|subscribe|consume|receive_message|receivemessage|produce|enqueue)\w*\s*\(",
    re.I,
)
STRING_LITERAL_RE = re.compile(r"[\"']([A-Za-z][\w.-]{2,})[\"']")
IMPORT_LINE_RE = re.compile(r"\b(?:import|from|require|using|new|use)\b")
GRPC_DIAL_RE = re.compile(
    r"""grpc\.(?:Dial|DialContext|NewClient)\s*\(\s*(?:\w+\s*,\s*)?["']([A-Za-z0-9.-]+)(?::\d+)?["']"""
)


@dataclass(frozen=True)
class TargetOption:
    id: str  # "A", "B", …
    ref: str  # RosterEntry.ref ("org/repo" | "org/repo#path")
    name: str
    kind: str  # component kind if known else "component"


@dataclass(frozen=True)
class LinkCandidate:
    source_path: str  # component path ("" = root)
    file: str
    line: int  # 1-based
    code: str  # snippet ±6 lines, ≤ 1500 chars
    reference: str  # the token as written (env var name, hostname, service name, image, sdk name)
    reference_kind: str
    options: tuple[TargetOption, ...]  # ≤ 6 roster shortlist
    external_name: str = ""  # code-derived name when the token looks external ("api.stripe.com" -> "stripe")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source_path, self.reference_kind, self.reference.lower())


@dataclass(frozen=True)
class LinkScan:
    candidates: tuple[LinkCandidate, ...]
    files_read: tuple[str, ...]  # every file the scanner opened, in order (feeds Evidence.files_read)


def find_link_candidates(
    tree: Iterable[str],
    read_file: Callable[[str], str | None],
    components: Sequence[ComponentDecl],
    roster: Sequence[RosterEntry],
    *,
    this_repo: str,
    limit: int = DEFAULT_LIMIT,
) -> LinkScan:
    """Scan one repository for link candidates.

    ``roster`` includes this repository's own components as siblings (the way
    ``refresh.py`` builds ``full_roster``) so a candidate can point at them.
    """
    scanner = _Scanner(list(tree), read_file, tuple(components), tuple(roster), this_repo)
    return scanner.run(limit)


def already_covered(candidate: LinkCandidate, topology: RepositoryTopology) -> bool:
    """True when the topology already draws this edge from the candidate's
    component: an internal dependency written as one of its options' exact
    refs (or the ``#path`` sibling form), or an external with the same
    canonical name.

    Only exact forms count on purpose. A loosely written target (a bare
    ``auth-service``, ``org/repo/path``) is a guess that ``resolve_ref`` may
    send to the wrong repository, and those guesses are exactly what the Jev
    stage should re-check: resolving them here hid five candidates on the
    messy-monorepo eval and lost the one edge Jev had recovered. Re-asking
    costs a fraction of a cent and ``resolve_topology`` dedupes the result.
    """
    refs = {o.ref.lower() for o in candidate.options}
    for dep in topology.internal:
        if dep.source_path != candidate.source_path:
            continue
        target = dep.target_ref.strip().lower()
        if target in refs:
            return True
        sibling = target if target.startswith("#") else "#" + target
        if any(r.endswith(sibling) for r in refs):
            return True
    if candidate.external_name:
        want = canonical_key(candidate.external_name)
        for ext in topology.externals:
            if ext.source_path == candidate.source_path and canonical_key(ext.name) == want:
                return True
    return False


# --- Tokens and hosts ---------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    return {t for t in TOKEN_SPLIT_RE.split((text or "").lower()) if len(t) > 1 and not t.isdigit()}


def _is_infra(token: str) -> bool:
    low = (token or "").lower()
    return low in INFRA_TERMS or any(t in INFRA_WORDS for t in _tokens(low))


@dataclass(frozen=True)
class _Host:
    name: str  # as written
    tokens: frozenset[str]
    external_name: str  # "" for localhost, IPs, docker/k8s names
    skip: bool = False  # docs / registries / examples: never a link


def _classify_host(host: str) -> _Host:
    low = host.lower().rstrip(".")
    if low in NON_SERVICE_HOSTS or low.startswith(NON_SERVICE_HOST_PREFIXES):
        return _Host(host, frozenset(), "", skip=True)
    labels = low.split(".")
    if all(label.isdigit() for label in labels):
        return _Host(host, frozenset(), "")
    if low.endswith(INTERNAL_HOST_SUFFIXES) or len(labels) == 1:
        return _Host(host, frozenset(_tokens(labels[0])), "")
    registrable = labels[-2]
    if len(labels) >= 3 and labels[-2] in SECOND_LEVEL_TLDS and len(labels[-1]) == 2:
        registrable = labels[-3]
    return _Host(host, frozenset(_tokens(low)), registrable)


def _hosts_in(text: str) -> list[_Host]:
    return [_classify_host(m.group(1)) for m in URL_RE.finditer(text)]


def _mask_userinfo(line: str) -> str:
    return URL_USERINFO_RE.sub(r"\1***@", line)


def _is_secret_reference(value: str) -> bool:
    return SECRET_REFERENCE_RE.match(value.strip().strip("\"'")) is not None


def _mask_secrets(line: str, previous: str = "") -> str:
    """A neighbouring line in a snippet: credential-looking keys keep their
    name and lose their value (also a k8s ``value:`` under ``- name: <key>``,
    which is why the ``previous`` line is passed); a value that merely
    references a secret is kept; ``user:pass@`` in URLs is dropped."""
    line = _mask_userinfo(line)
    m = SECRET_LINE_RE.match(line)
    if m is None and K8S_SECRET_NAME_RE.match(previous):
        m = K8S_VALUE_LINE_RE.match(line)
    if m is None or _is_secret_reference(m.group(2)):
        return line
    return m.group(1) + "***"


def _snippet(lines: Sequence[str], line_no: int) -> str:
    """The line plus up to ±SNIPPET_RADIUS neighbours, grown outwards until the
    character budget is spent, so the matched line is always inside.

    The matched line names a service (its key and hostname stay), so it is
    only userinfo-masked; its neighbours are secret-masked so an ``.env``
    next to it never leaks a secret."""
    centre = max(0, min(line_no - 1, len(lines) - 1))
    picked = {centre: _mask_userinfo(lines[centre][:SNIPPET_CHARS])}
    total = len(picked[centre])
    for offset in range(1, SNIPPET_RADIUS + 1):
        for idx in (centre - offset, centre + offset):
            if 0 <= idx < len(lines):
                cost = len(lines[idx]) + 1
                if total + cost > SNIPPET_CHARS:
                    continue
                picked[idx] = _mask_secrets(lines[idx], lines[idx - 1] if idx else "")
                total += cost
    return "\n".join(picked[i] for i in sorted(picked))


def _line_of(lines: Sequence[str], needle: str, start: int = 1) -> int:
    """1-based line containing ``needle`` at or after ``start``; ``start`` when absent."""
    for idx in range(max(0, start - 1), len(lines)):
        if needle in lines[idx]:
            return idx + 1
    return start


# --- File selection -------------------------------------------------------------------


def _is_skipped(path: str) -> bool:
    return is_noise(path) or in_dirs(path, DATA_DIRS)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1].lower()


def _image_name(image: str) -> str:
    """``image`` without its tag or digest. Only the last path segment carries
    one, so a registry port survives: ``localhost:5000/org/repo:tag`` →
    ``localhost:5000/org/repo``; ``reg.io:5000/org/repo`` is unchanged."""
    head, sep, last = image.strip().rpartition("/")
    return head + sep + re.split(r"[:@]", last, maxsplit=1)[0]


def _is_compose(path: str) -> bool:
    return COMPOSE_FILE_RE.match(_basename(path)) is not None


def _is_k8s_family(path: str) -> bool:
    return _basename(path).endswith((".yml", ".yaml")) and in_dirs(path, DEPLOY_DIRS)


def _is_scannable(path: str) -> bool:
    base = _basename(path)
    if base in LOCK_FILES or base.endswith((".min.js", ".map", ".d.ts")):
        return False
    return base.startswith(".env") or base in MANIFEST_BASENAMES or base.endswith(CONFIG_SUFFIXES + SOURCE_SUFFIXES)


def _tier(path: str) -> int:
    """Read order inside a component: env files, manifests, config, source, other json."""
    base = _basename(path)
    if base.startswith(".env"):
        return 0
    if base in MANIFEST_BASENAMES:
        return 1
    if base.endswith((".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties")):
        return 2
    if base.endswith(SOURCE_SUFFIXES):
        return 3
    return 4


def _file_order(path: str) -> tuple[int, int, str]:
    return (_tier(path), path.count("/"), path)


# --- The scanner ------------------------------------------------------------------------


class _Scanner:
    def __init__(self, tree, read_file, components, roster, this_repo):
        self._tree = [p for p in tree if not _is_skipped(p)]
        self._read_file = read_file
        self._components = components
        self._roster = roster
        self._this_repo = this_repo.lower()
        self._by_path = {c.path: c for c in components}
        self._cache: dict[str, str | None] = {}
        self._files_read: list[str] = []
        self._found: dict[tuple[str, str, str], LinkCandidate] = {}
        self._entry_tokens = {
            e.ref: _tokens(canonical_key(e.name)) | _tokens(e.path.rsplit("/", 1)[-1]) | _tokens(e.full_path.rsplit("/", 1)[-1])
            for e in roster
        }
        self._common = self._common_repo_tokens()

    # -- driver --

    def run(self, limit: int) -> LinkScan:
        self._scan_structural()
        for source, files in self._files_by_component().items():
            for path in files:
                text = self._read(path)
                if text is None:
                    continue
                base = _basename(path)
                self._scan_lines(
                    source, path, text,
                    manifest=base in MANIFEST_BASENAMES,
                    source_code=base.endswith(SOURCE_SUFFIXES),
                )
        ordered = sorted(
            self._found.values(),
            key=lambda c: (REFERENCE_KINDS.index(c.reference_kind), c.file, c.line),
        )
        return LinkScan(candidates=tuple(ordered[:limit]), files_read=tuple(self._files_read))

    def _read(self, path: str) -> str | None:
        if path not in self._cache:
            text = self._read_file(path)
            if text is not None:
                self._files_read.append(path)
                if len(text) > MAX_FILE_CHARS:
                    text = None
            self._cache[path] = text
        return self._cache[path]

    def _files_by_component(self) -> dict[str, list[str]]:
        """Each component's own scannable files (nested components excluded;
        the root also skips docs/legacy/tooling folders).

        A file nobody owns is skipped. Root-level manifests in a repository
        whose root is not a component are the common case of that: handing
        them to every component would give each one the root's links (the
        eval on the messy monorepo showed a wrong discovery turning one
        ``AUTH0_DOMAIN`` into a dozen ``→ Auth0`` edges). Compose and k8s
        files are attributed by service name, not ownership, so they are
        not affected."""
        files: dict[str, list[str]] = {c.path: [] for c in self._components}
        for path in self._tree:
            if not _is_scannable(path) or _is_compose(path) or _is_k8s_family(path):
                continue
            owner = self._component_containing(path.rsplit("/", 1)[0] if "/" in path else "")
            if owner is None:
                continue
            if owner == "" and path.split("/")[0] in ROOT_ONLY_SKIP_DIRS:
                continue
            files[owner].append(path)
        for paths in files.values():
            paths.sort(key=_file_order)
            del paths[MAX_FILES_PER_COMPONENT:]
        return files

    # -- roster helpers --

    def _common_repo_tokens(self) -> set[str]:
        """Tokens shared by most repositories in the workspace (an org prefix
        like ``gitgrit-demo``) — they discriminate nothing."""
        repos = {e.full_path.lower() for e in self._roster}
        if len(repos) < 3:
            return set()
        counts: dict[str, int] = {}
        for repo in repos:
            for t in _tokens(repo.rsplit("/", 1)[-1]):
                counts[t] = counts.get(t, 0) + 1
        return {t for t, n in counts.items() if n >= max(3, len(repos) // 2)}

    def _is_self(self, source_path: str, entry: RosterEntry) -> bool:
        return entry.full_path.lower() == self._this_repo and entry.path == source_path

    def _sibling(self, path: str) -> RosterEntry | None:
        for e in self._roster:
            if e.full_path.lower() == self._this_repo and e.path == path:
                return e
        return None

    def _option_kind(self, entry: RosterEntry) -> str:
        if entry.full_path.lower() == self._this_repo and entry.path in self._by_path:
            return self._by_path[entry.path].kind
        return "component"

    def _shortlist(
        self, source_path: str, tokens: set[str], pinned: Iterable[RosterEntry] = ()
    ) -> tuple[TargetOption, ...] | None:
        """Roster entries sharing a token with the reference, best first,
        siblings before other repositories. None when the reference names the
        source component itself (a same-named repo elsewhere does not rescue it)."""
        pinned_refs = {e.ref for e in pinned}
        strong = {t for t in tokens if t not in GENERIC_WORDS and t not in self._common}

        def rank(words: set[str]) -> list[tuple[int, bool, str, RosterEntry]]:
            rows = []
            for e in self._roster:
                score = len(words & self._entry_tokens[e.ref]) + (10 if e.ref in pinned_refs else 0)
                if score:
                    rows.append((-score, e.full_path.lower() != self._this_repo, e.ref, e))
            return sorted(rows)

        ranked = rank(strong) or rank(tokens & WEAK_WORDS)
        if ranked and self._is_self(source_path, ranked[0][3]):
            return None
        seen: set[str] = set()
        options: list[TargetOption] = []
        for _, _, ref, entry in ranked:
            if ref in seen or self._is_self(source_path, entry):
                continue
            seen.add(ref)
            options.append(TargetOption(chr(ord("A") + len(options)), ref, entry.name, self._option_kind(entry)))
            if len(options) >= MAX_OPTIONS:
                break
        return tuple(options)

    def _component_containing(self, directory: str) -> str | None:
        best = None
        for c in self._components:
            if c.path == "" or directory == c.path or directory.startswith(c.path + "/"):
                if best is None or len(c.path) > len(best):
                    best = c.path
        return best

    def _component_by_name(self, name: str) -> str | None:
        low = (name or "").lower()
        for c in self._components:
            if low and (c.name.lower() == low or c.path.rsplit("/", 1)[-1].lower() == low):
                return c.path
        words = {t for t in _tokens(low) if t not in GENERIC_WORDS and t not in self._common}
        scored = sorted(
            ((len(words & (_tokens(c.name) | _tokens(c.path.rsplit("/", 1)[-1]))), c.path) for c in self._components),
            reverse=True,
        )
        if scored and scored[0][0] and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            return scored[0][1]
        return None

    def _repo_entries_for_image(self, image: str) -> list[RosterEntry]:
        """Roster entries an image name points at: ``ghcr.io/org/repo[:tag]`` is
        repo ``org/repo``'s root; ``ghcr.io/org/mono/svc`` is component ``svc``
        of ``org/mono``; otherwise a repo whose last segment equals the image's."""
        parts = [p for p in _image_name(image).split("/") if p]
        if parts and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
            parts = parts[1:]  # registry host
        if not parts:
            return []
        full = "/".join(parts)
        entry = resolve_ref(full, self._roster)
        if entry is not None and entry.full_path.lower() == full.lower():
            return [entry]  # the repository itself
        if len(parts) >= 3:
            repo, component = "/".join(parts[:-1]).lower(), parts[-1].lower()
            for e in self._roster:
                if e.full_path.lower() == repo and component in (e.name.lower(), e.path.rsplit("/", 1)[-1].lower()):
                    return [e]
        return [entry] if entry is not None else []

    # -- emitting --

    def _add(
        self,
        source_path: str,
        file: str,
        line_no: int,
        lines: Sequence[str],
        reference: str,
        kind: str,
        tokens: set[str],
        *,
        pinned: Iterable[RosterEntry] = (),
        external_name: str = "",
    ) -> None:
        key = (source_path, kind, reference.lower())
        if key in self._found:
            return  # first sighting wins; no shortlist or snippet work for repeats
        options = self._shortlist(source_path, tokens, pinned)
        if options is None or (not options and not external_name):
            return  # its own component, or nothing it can mean
        self._found[key] = LinkCandidate(
            source_path=source_path,
            file=file,
            line=line_no,
            code=_snippet(lines, line_no),
            reference=reference,
            reference_kind=kind,
            options=options,
            external_name=external_name,
        )

    # -- structural files: compose and k8s --

    def _scan_structural(self) -> None:
        k8s_files: list[tuple[str, list[dict]]] = []
        service_names: set[str] = set()
        for path in self._tree:
            if _is_compose(path):
                text = self._read(path)
                if text is not None:
                    self._scan_compose(path, text)
            elif _is_k8s_family(path):
                text = self._read(path)
                if text is None:
                    continue
                docs = _yaml_docs(text)
                if docs:
                    k8s_files.append((path, docs))
                    service_names.update(_k8s_service_names(docs))
                else:
                    owner = self._component_by_name(path.split("/")[-2] if "/" in path else "")
                    if owner is not None:  # helm values.yaml: plain config, owned by the chart's component
                        self._scan_lines(owner, path, text, manifest=False, source_code=False)
        for path, docs in k8s_files:
            self._scan_k8s(path, docs, service_names)

    def _scan_compose(self, path: str, text: str) -> None:
        try:
            data = yaml.safe_load(text)
        except (yaml.YAMLError, RecursionError):  # PyYAML's own composer recurses on deep documents
            return
        services = data.get("services") if isinstance(data, dict) else None
        if not isinstance(services, dict):
            return
        base_dir = path.rsplit("/", 1)[0] if "/" in path else ""
        lines = text.splitlines()
        specs = {name: spec for name, spec in services.items() if isinstance(spec, dict)}
        owners = {name: self._compose_owner(spec, base_dir) for name, spec in specs.items()}
        dependents: dict[str, list[str]] = {}

        for name, spec in specs.items():
            source = owners[name]
            header = _line_of(lines, f"{name}:")
            for dep in _compose_depends_on(spec):
                dependents.setdefault(dep, []).append(name)
                if source is None or _is_infra(dep):
                    continue
                pinned: list[RosterEntry] = []
                target_owner = owners.get(dep)
                if target_owner is not None:
                    pinned += [e for e in [self._sibling(target_owner)] if e is not None]
                elif isinstance(specs.get(dep, {}).get("image"), str):
                    pinned += self._repo_entries_for_image(specs[dep]["image"])
                self._add(source, path, _line_of(lines, dep, header), lines, dep, "compose_depends_on", _tokens(dep), pinned=pinned)
            for env_name, value in _compose_environment(spec):
                if source is not None:
                    self._scan_env_pair(source, path, _line_of(lines, env_name, header), lines, env_name, value)

        for name, spec in specs.items():
            image = spec.get("image")
            if owners[name] is not None or not isinstance(image, str) or _is_infra(image):
                continue
            sources = [owners[s] for s in dependents.get(name, ()) if owners[s] is not None]
            if not sources and "" in self._by_path:
                sources = [""]
            pinned = self._repo_entries_for_image(image)
            last = _image_name(image).rsplit("/", 1)[-1]
            for source in dict.fromkeys(sources):
                self._add(
                    source, path, _line_of(lines, image, _line_of(lines, f"{name}:")), lines, image, "image",
                    _tokens(name) | _tokens(last), pinned=pinned, external_name="" if pinned else last,
                )

    def _compose_owner(self, spec: dict, base_dir: str) -> str | None:
        build = spec.get("build")
        context = build if isinstance(build, str) else build.get("context") if isinstance(build, dict) else None
        if context is None:
            return None  # pulled image: not built from this repository
        directory = clean_path(posixpath.normpath(posixpath.join(base_dir, _scalar(context))))
        return self._component_containing(directory)

    def _scan_k8s(self, path: str, docs: list[dict], service_names: set[str]) -> None:
        lines = self._cache[path].splitlines() if self._cache.get(path) else []
        for doc in docs:
            if doc.get("kind") not in K8S_WORKLOAD_KINDS:
                continue
            meta_name = _k8s_name(doc)
            owner = self._component_by_name(meta_name)
            if owner is None:
                for container in _k8s_containers(doc):
                    owner = self._component_by_name(_scalar(container.get("name"))) or self._component_by_name(
                        _image_name(_scalar(container.get("image"))).rsplit("/", 1)[-1]
                    )
                    if owner is not None:
                        break
            if owner is None:
                continue
            for env_name, value in _k8s_env_pairs(doc):
                line_no = _line_of(lines, env_name)
                hosts = _hosts_in(value) or ([_classify_host(value)] if BARE_HOST_RE.match(value) or value in service_names else [])
                svc = next((h.name.split(".")[0] for h in hosts if h.name.split(".")[0] in service_names), "")
                if svc:
                    if svc.lower() == meta_name.lower() or self._component_by_name(svc) == owner:
                        continue  # its own Service
                    sibling = self._component_by_name(svc)
                    pinned = [e for e in [self._sibling(sibling)] if sibling is not None and e is not None]
                    self._add(owner, path, line_no, lines, svc, "k8s_ref", _tokens(svc), pinned=pinned)
                else:
                    self._scan_env_pair(owner, path, line_no, lines, env_name, value)

    # -- line scanning --

    def _scan_lines(self, source: str, file: str, text: str, *, manifest: bool, source_code: bool) -> None:
        lines = text.splitlines()
        for line_no, line in enumerate(lines, 1):
            if not line.strip():
                continue
            if not self._scan_env_line(source, file, line_no, lines, line):
                for host in _hosts_in(line):
                    self._add_host(source, file, line_no, lines, host, "url")
            self._scan_queue_line(source, file, line_no, lines, line, source_code=source_code)
            if manifest or (source_code and IMPORT_LINE_RE.search(line)):
                for name in sorted(_tokens(line) & SDK_NAMES):
                    self._add(source, file, line_no, lines, name, "sdk_client", {name}, external_name=name)
            if source_code:
                for m in GRPC_DIAL_RE.finditer(line):
                    self._add_host(source, file, line_no, lines, _classify_host(m.group(1)), "sdk_client")

    def _add_host(self, source: str, file: str, line_no: int, lines: Sequence[str], host: _Host, kind: str) -> None:
        if host.skip or _is_infra(host.name):
            return
        self._add(source, file, line_no, lines, host.name, kind, set(host.tokens), external_name=host.external_name)

    def _scan_env_line(self, source: str, file: str, line_no: int, lines: Sequence[str], line: str) -> bool:
        """Env-var style names on the line. Hosts on the same line only enrich
        the env candidate (they are not emitted as separate ``url`` ones)."""
        matches = list(ENV_VAR_RE.finditer(line))
        if not matches:
            return False
        hosts = [h for h in _hosts_in(line) if not h.skip]
        for m in matches:
            assigned = ASSIGNED_VALUE_RE.match(line, m.end())
            self._scan_env_pair(source, file, line_no, lines, m.group(1), assigned.group(1) if assigned else "", hosts)
        return True

    def _env_found(self, source: str, name: str) -> bool:
        """First sighting wins: a repeat is dropped before any shortlist work."""
        return (source, "env_var", name.lower()) in self._found

    def _scan_env_pair(
        self,
        source: str,
        file: str,
        line_no: int,
        lines: Sequence[str],
        name: str,
        value: str,
        hosts: Sequence[_Host] | None = None,
    ) -> None:
        """One ``NAME=value`` pair, from a line or straight out of a compose /
        k8s document. ``hosts`` are the hosts on the line it came from (a
        default in ``process.env.X ?? 'http://…'`` counts); by default the
        value's own."""
        if not ENV_VAR_RE.fullmatch(name) or self._env_found(source, name):
            return
        if hosts is None:
            hosts = [h for h in _hosts_in(value) if not h.skip]
        token = VALUE_TOKEN_RE.match(value)
        value = token.group(1) if token else ""
        scheme = SCHEME_RE.match(value)
        if _is_infra(name) or (scheme and _is_infra(scheme.group(1))) or any(_is_infra(h.name) for h in hosts):
            return
        own_hosts = list(hosts)
        if not own_hosts and BARE_HOST_RE.match(value):
            own_hosts.append(_classify_host(value.split(":")[0]))
        tokens = _tokens(name)
        for h in own_hosts:
            tokens |= h.tokens
        external = next((h.external_name for h in own_hosts if h.external_name), "")
        self._add(source, file, line_no, lines, name, "env_var", tokens, external_name=external)

    def _scan_queue_line(self, source, file, line_no, lines, line, *, source_code: bool) -> None:
        names: list[str] = []
        key = QUEUE_KEY_RE.match(line)
        if key and not ENV_VAR_RE.search(key.group(1)):
            value = key.group(2)
            names.append(value.rstrip("/").rsplit("/", 1)[-1] if SCHEME_RE.match(value) else value)
        if source_code and QUEUE_CALL_RE.search(line):
            names += [m.group(1) for m in STRING_LITERAL_RE.finditer(line)]
        for name in names:
            if _is_infra(name) or SCHEME_RE.match(name) or name.lower() in GENERIC_WORDS:
                continue
            self._add(source, file, line_no, lines, name, "queue_name", _tokens(name))


# --- YAML helpers -------------------------------------------------------------------------


def _scalar(node) -> str:
    """A YAML scalar as text; "" for a container or null. Never ``str()`` a
    node blindly: an aliased DAG's repr is exponential in its depth."""
    return str(node) if isinstance(node, (str, int, float, bool)) else ""


def _k8s_name(doc: dict) -> str:
    """``metadata.name`` when it is a string; "" for anything else
    (``metadata: foo`` is a malformed manifest, not a reason to abort)."""
    metadata = doc.get("metadata")
    name = metadata.get("name") if isinstance(metadata, dict) else None
    return name if isinstance(name, str) else ""


def _yaml_docs(text: str) -> list[dict]:
    """Kubernetes documents (dicts with a ``kind``); [] on parse errors or plain config."""
    try:
        docs = list(yaml.safe_load_all(text))
    except (yaml.YAMLError, RecursionError):  # PyYAML's own composer recurses on deep documents
        return []
    return [d for d in docs if isinstance(d, dict) and isinstance(d.get("kind"), str)]


def _walk(root, visit: Callable[[dict], Iterable | None]) -> None:
    """Depth-first over the dicts and lists under ``root``. ``visit(node)`` is
    called on every dict and may return the children to descend into instead
    of all of its values. Each container is entered once — YAML aliases turn
    a document into a DAG or a cycle (``&a [*a]``) — and depth is capped."""
    seen: set[int] = set()

    def go(node, depth: int) -> None:
        if depth > MAX_YAML_DEPTH or not isinstance(node, (dict, list)) or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, dict):
            children = visit(node)
            children = node.values() if children is None else children
        else:
            children = node
        for child in children:
            go(child, depth + 1)

    go(root, 0)


def _k8s_service_names(docs: list[dict]) -> set[str]:
    names: set[str] = set()
    for doc in docs:
        name = _k8s_name(doc)
        if doc.get("kind") == "Service" and name:
            names.add(name)
        if doc.get("kind") == "Ingress":
            names.update(_ingress_backends(doc))
    return names


def _ingress_backends(doc: dict) -> set[str]:
    out: set[str] = set()

    def visit(node: dict) -> None:
        svc = node.get("service")
        if isinstance(svc, dict) and isinstance(svc.get("name"), str):
            out.add(svc["name"])
        if isinstance(node.get("serviceName"), str):
            out.add(node["serviceName"])

    _walk(doc.get("spec"), visit)
    return out


def _k8s_containers(doc: dict) -> list[dict]:
    out: list[dict] = []

    def visit(node: dict) -> list:
        rest = []
        for key, value in node.items():
            if key in ("containers", "initContainers") and isinstance(value, list):
                out.extend(c for c in value if isinstance(c, dict))
            else:
                rest.append(value)
        return rest

    _walk(doc.get("spec"), visit)
    return out


def _k8s_env_pairs(doc: dict) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if doc.get("kind") == "ConfigMap":
        data = doc.get("data") or {}
        if isinstance(data, dict):
            pairs += [(_scalar(k), _scalar(v)) for k, v in data.items() if isinstance(v, (str, int))]
        return pairs
    for container in _k8s_containers(doc):
        for item in container.get("env") or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("value"), (str, int)):
                pairs.append((item["name"], _scalar(item["value"])))
    return pairs


def _compose_depends_on(spec: dict) -> list[str]:
    deps = spec.get("depends_on")
    if isinstance(deps, (list, dict)):
        return [name for name in map(_scalar, deps) if name]
    return []


def _compose_environment(spec: dict) -> list[tuple[str, str]]:
    """``(name, value)`` pairs from either compose form: ``- K=V`` or ``K: V``."""
    env = spec.get("environment")
    if isinstance(env, list):
        return [(k, v) for k, v in (_scalar(e).split("=", 1) for e in env if "=" in _scalar(e))]
    if isinstance(env, dict):
        return [(_scalar(k), _scalar(v)) for k, v in env.items() if v is not None]
    return []
