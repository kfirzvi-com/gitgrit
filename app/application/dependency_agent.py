"""LLM dependency-inference use case.

Runs the in-process agent (``app.infrastructure.llm_agent``) against one
project's repository: the model lists/reads whatever config, IaC, manifest or
build files it judges relevant and returns the project's dependencies. We then
resolve those against the workspace's component roster — known components
become ``ComponentDependency`` edges, everything else becomes an
``ExternalDependency`` (third-party) — replacing the project's existing edges
atomically.

Edges, infrastructure and tech labels are written to the project's *root
component* (the repository as one deployable unit). Discovering several
components inside one repository is the next step on top of this.

Stack-to-stack edges are NOT written here; they're derived at read time
(see ``app.presentation.architecture``).
"""
from __future__ import annotations

import logging
from typing import Annotated

from django.db import transaction
from django.utils import timezone
from pydantic import BaseModel, Field

from app.application.naming import canonical_key
from app.application.standard_engine import resolve_llm_roles
from app.domain.models import (
    Component,
    ComponentDependency,
    ExternalDependency,
    InfrastructureComponent,
    Project,
)
from app.infrastructure.llm_agent import LLMAgent, tool
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger(__name__)

ROLE = "reasoning"

# Backstop: common self-operated datastores/queues/storage. If the model files
# one of these as an external service, we reclassify it as infrastructure.
_INFRA_TERMS = {
    "postgres": "database", "postgresql": "database", "mysql": "database",
    "mariadb": "database", "sqlite": "database", "mongodb": "database",
    "mongo": "database", "dynamodb": "database", "cassandra": "database",
    "cockroach": "database", "rds": "database", "aurora": "database",
    "redis": "cache", "memcached": "cache",
    "kafka": "queue", "rabbitmq": "queue", "sqs": "queue", "sns": "queue",
    "kinesis": "queue", "pubsub": "queue", "nats": "queue",
    "s3": "storage", "gcs": "storage", "minio": "storage", "blob storage": "storage",
    "elasticsearch": "database", "opensearch": "database",
}


# Bare cloud providers aren't a specific external service — the concrete
# managed services (S3, SQS, RDS) are captured as infrastructure instead.
_GENERIC_CLOUD = {
    "aws", "amazon web services", "amazon", "gcp", "google cloud",
    "google cloud platform", "azure", "microsoft azure",
}


def _infra_kind(name: str) -> str | None:
    """Return an infrastructure kind if the name is a known datastore/queue, else None."""
    n = (name or "").lower()
    for term, kind in _INFRA_TERMS.items():
        if term in n:
            return kind
    return None



_SYSTEM_PROMPT = (
    "You are mapping the dependencies of one software repository for an "
    "architecture diagram. Use the tools to inspect the repo yourself: list "
    "files and read the ones that reveal dependencies — manifests and lockfiles "
    "(package.json, go.mod, pyproject.toml, requirements, Gemfile, etc.), "
    "infrastructure-as-code (Terraform, Helm, k8s, docker-compose), service "
    "config and env files, CI config, and any code/config that references other "
    "services or third-party APIs. Use your judgment about what's worth reading — "
    "you do NOT need to read everything; skip bulk application source. "
    "The graph shows COMPONENTS (deployable systems/services), not libraries. "
    "Classify what you find into one of:\n"
    "  • technologies — languages, frameworks, libraries, SDKs and tools the "
    "repo USES (e.g. Next.js, React, FastAPI, Express, Terraform, the AWS SDK, "
    "zod, pydantic). These are NOT graph nodes — they become the component's "
    "tech labels. Put every imported package/framework/tool here.\n"
    "  • internal — a dependency on ANOTHER component in this workspace; only "
    "use the components listed in the roster, and return the component's "
    "exact ref as the target (a repository's full_path, or full_path#path for "
    "a component inside a monorepo).\n"
    "  • infrastructure — a datastore/queue/cache/object-store the service OWNS "
    "and operates as its own implementation detail (its Postgres/MySQL/Mongo "
    "database, Redis cache, Kafka/RabbitMQ/SQS queue, S3 bucket). These are "
    "stack-INTERNAL components, not external services. Give each a `kind` of "
    "database, cache, queue, or storage.\n"
    "  • external_provider — a TRUE third-party SERVICE operated by another "
    "company that THIS repo integrates with over the network: SaaS/APIs like "
    "Stripe, Auth0, SendGrid, Twilio, an external partner API. Do NOT put "
    "databases, caches, queues, object storage, or your own cloud infra here — "
    "those go in infrastructure. A client library/SDK is NOT a provider either — "
    "the SDK goes in technologies, the third-party service it calls goes here "
    "(e.g. 'Stripe SDK' is a technology, 'Stripe' is a provider). Do NOT list a "
    "bare cloud provider (AWS, GCP, Azure) — list the specific managed service "
    "as infrastructure instead.\n"
    "  • external_consumer — a system OUTSIDE the workspace that depends on THIS "
    "repo (i.e. this repo exposes something it consumes). NEVER list a roster "
    "repository here — when a workspace repo consumes this one, that's captured "
    "as the other repo's internal dependency, not here. Infer external consumers "
    "only from real evidence in the repo: a public/published API or OpenAPI "
    "spec, a package published for outside use, inbound webhook endpoints the "
    "repo receives (the external sender is the consumer), CORS allow-lists or "
    "registered external client IDs, or docs naming external clients. Be "
    "conservative — omit if there's no clear signal.\n"
    "Note a third party can be BOTH (e.g. you call Stripe's API = provider, and "
    "Stripe calls your webhook = consumer). Do not include this repository "
    "itself or other workspace repos as external. When you have enough evidence, "
    "stop calling tools and return the structured result."
)


class _InternalDep(BaseModel):
    target: str = Field(description="ref of a roster component this repo depends on")
    label: str = Field(default="", description="short edge caption, e.g. 'REST', 'events', 'OAuth'")


class _ExternalDep(BaseModel):
    name: str = Field(description="external system/service name, e.g. 'Stripe'")
    url: str = Field(default="", description="homepage/docs url if known")
    label: str = Field(default="", description="short caption, e.g. 'payments', 'webhooks'")


class _InfraDep(BaseModel):
    name: str = Field(description="datastore/queue/cache name, e.g. 'PostgreSQL'")
    kind: str = Field(default="other", description="database | cache | queue | storage")
    label: str = Field(default="", description="short caption, e.g. 'orders DB'")


class DependencyResult(BaseModel):
    technologies: list[str] = Field(
        default=[],
        description="languages/frameworks/libraries/tools used (tech labels, not nodes)",
    )
    internal: list[_InternalDep] = []
    infrastructure: list[_InfraDep] = Field(
        default=[], description="self-operated datastores/queues this service owns"
    )
    external_providers: list[_ExternalDep] = Field(
        default=[], description="true third-party services this repo depends on"
    )
    external_consumers: list[_ExternalDep] = Field(
        default=[], description="external systems that depend on this repo"
    )


# Directories that are never dependency evidence and routinely dwarf the rest
# of the tree (committed node_modules, build output). Hidden from listings so
# the real manifests fit inside the tool-result cap; read_file can still open
# anything inside them.
_NOISE_DIRS = frozenset({
    "node_modules", "vendor", "dist", "build", "target", "__pycache__",
    ".git", ".terraform", ".venv", "venv", ".idea", ".vscode",
})
# Basenames worth pointing the model at when a tree is too big to list whole.
_MANIFEST_NAMES = frozenset({
    "package.json", "pyproject.toml", "requirements.txt", "pipfile", "go.mod",
    "cargo.toml", "gemfile", "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "mix.exs", "package.swift", "pubspec.yaml", "dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "readme.md", ".env.example", ".env.sample", ".env.template", "serverless.yml",
    "main.tf", "variables.tf", "chart.yaml", "values.yaml", "procfile", "makefile",
})
_MANIFEST_SUFFIXES = (".csproj", ".fsproj", ".tf", ".sln")
MAX_LISTING_ENTRIES = 400


def _is_noise(path: str) -> bool:
    return any(part in _NOISE_DIRS for part in path.split("/")[:-1])


def _looks_like_manifest(path: str) -> bool:
    base = path.rsplit("/", 1)[-1].lower()
    return base in _MANIFEST_NAMES or base.endswith(_MANIFEST_SUFFIXES)


def _clean_path(path) -> str:
    """Normalize a model-supplied path: strip whitespace, backslashes, leading
    './' and surrounding slashes. '', '.', './' and '/' all become ''."""
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


class _RepoToolbox:
    """Read-only repository tools handed to the model.

    Records what the model actually inspected (``tree_size``, ``files_read``)
    so the caller can refuse to save an answer that was never grounded in the
    repo — a model that reads nothing and guesses must not produce an ``ok`` map.

    Every tool returns a string the model can act on. An empty list or empty
    string is never returned for a miss: models that get silence retry the same
    wrong argument until the round-trip cap and then invent a result.
    """

    def __init__(self, client, full_path: str, ref: str):
        self._client = client
        self._full_path = full_path
        self._ref = ref
        self._tree: list[str] | None = None
        self.tree_size: int | None = None  # None until list_repo_files ran
        self.files_read: list[str] = []

    def _root_aliases(self) -> set[str]:
        # Models name the root as '', '.', '/', the repo's full path or its name.
        return {"", ".", self._full_path.lower(), self._full_path.rsplit("/", 1)[-1].lower()}

    def _load_tree(self) -> list[str]:
        if self._tree is None:
            raw = self._client.get_tree(self._full_path, self._ref) or []
            self.tree_size = len(raw)
            self._tree = [p for p in raw if not _is_noise(p)]
        return self._tree

    @tool
    def list_repo_files(
        self,
        path: Annotated[
            str,
            "Directory path relative to the repository root, e.g. 'src' or "
            "'infra/terraform'. Pass '' (or '.' or '/') to list the whole repository.",
        ] = "",
    ) -> str:
        """List the repository's files, one path per line.

        With no path (or '.', '/') lists the whole repository; a large repository
        gets a directory summary plus every manifest/config file found anywhere.
        With a directory path lists only the files under it. Generated and
        dependency folders (node_modules, vendor, dist, …) are hidden.
        """
        tree = self._load_tree()
        if not tree:
            return "The repository listing is empty (no readable files on this branch)."

        p = _clean_path(path)
        if p.lower() in self._root_aliases():
            return self._list_root(tree)

        prefix = p + "/"
        matches = [f for f in tree if f.startswith(prefix)]
        if not matches:
            top = sorted({f.split("/", 1)[0] for f in tree})
            return (
                f"No files under '{path}'. Top-level entries: {', '.join(top[:60])}. "
                "Pass '' to list the whole repository."
            )
        return self._render(matches, f"under '{p}'")

    def _list_root(self, tree: list[str]) -> str:
        if len(tree) <= MAX_LISTING_ENTRIES:
            return "\n".join(tree)
        counts: dict[str, int] = {}
        root_files = []
        for f in tree:
            if "/" in f:
                d = f.split("/", 1)[0]
                counts[d] = counts.get(d, 0) + 1
            else:
                root_files.append(f)
        lines = [f"{len(tree)} files. Root files:", *root_files, "", "Directories (file count):"]
        lines += [f"{d}/ ({n})" for d, n in sorted(counts.items())]
        manifests = [f for f in tree if "/" in f and _looks_like_manifest(f)]
        if manifests:
            lines += ["", "Manifest/config files in subdirectories:", *manifests[:150]]
        lines += ["", "Call list_repo_files(path='<directory>') to see the files in one directory."]
        return "\n".join(lines)

    @staticmethod
    def _render(paths: list[str], where: str) -> str:
        shown = paths[:MAX_LISTING_ENTRIES]
        out = "\n".join(shown)
        if len(paths) > len(shown):
            out += (
                f"\n… {len(paths) - len(shown)} more files {where}; "
                "pass a deeper directory path to see them."
            )
        return out

    @tool
    def read_file(
        self,
        path: Annotated[
            str, "File path relative to the repository root, exactly as list_repo_files shows it"
        ],
    ) -> str:
        """Read a text file and return its contents.

        Returns a '[no readable file at …]' message when the path does not exist
        or is not a text file — check list_repo_files for the exact path.
        """
        p = _clean_path(path)
        content = self._client.get_file_content(self._full_path, p, self._ref)
        if content is None:
            return (
                f"[no readable file at '{path}' — it is missing or binary. "
                "Use list_repo_files to find the exact path.]"
            )
        self.files_read.append(p)
        return content if content else f"[file '{p}' exists but is empty]"


def _ref(r: dict) -> str:
    """A roster entry's ref: ``full_path`` for a root component,
    ``full_path#path`` for a component inside a monorepo."""
    return r["full_path"] if not r["path"] else f"{r['full_path']}#{r['path']}"


def _build_instructions(project: Project, roster: list[dict]) -> str:
    lines = [
        f"Repository to analyze: {project.full_path}",
        "",
        "Workspace components (roster) you may reference as internal targets:",
    ]
    for r in roster:
        where = f"repo: {r['full_path']}" if r["path"] else f"name: {r['name']}"
        lines.append(f"  - ref: {_ref(r)}  ({where})")
    lines += [
        "",
        "Inspect the repository and return its internal and external dependencies.",
    ]
    return "\n".join(lines)


def _component_roster(tenant, project: Project) -> list[dict]:
    """Every other component in the workspace, flattened for prompt + resolution."""
    rows = (
        Component.objects.filter(tenant=tenant)
        .exclude(project=project)
        .values("pk", "name", "path", "project__full_path")
    )
    return [
        {"pk": r["pk"], "name": r["name"], "path": r["path"], "full_path": r["project__full_path"]}
        for r in rows
    ]


def _resolve_internal_target(target: str, roster: list[dict]) -> str | None:
    """Map an LLM-returned target string to a roster component id (best effort).

    Tried in order: exact ref (``repo`` or ``repo#path``); a bare repository
    whose only component is the root; ``repo/path`` slash form; a unique
    component name; a repository's last path segment (its root component).
    """
    t = (target or "").strip().lower().rstrip("/")
    if not t:
        return None
    by_ref = {_ref(r).lower(): r["pk"] for r in roster}
    if t in by_ref:
        return by_ref[t]
    # ``repo/path`` written with a slash instead of ``#``.
    for r in roster:
        if r["path"] and t == f"{r['full_path']}/{r['path']}".lower():
            return r["pk"]
    by_name = {}
    for r in roster:
        by_name.setdefault(r["name"].lower(), []).append(r["pk"])
    roots_by_last = {
        r["full_path"].lower().rsplit("/", 1)[-1]: r["pk"] for r in roster if not r["path"]
    }
    last = t.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    for key in (t, last):
        pks = by_name.get(key)
        if pks and len(pks) == 1:
            return pks[0]
    return roots_by_last.get(last)


def _root_component(project: Project) -> Component:
    root = project.root_component
    if root is None:  # invariant: created with the project; heal if missing
        root = Component.objects.create(
            tenant_id=project.tenant_id, project=project, path="", name=project.name
        )
    return root


def infer_and_store(project: Project) -> DependencyResult:
    """Analyze one project's repo and replace its dependency edges. Returns the
    raw model result. Sets the project's deps_status to OK on success; raises on
    failure (the caller/task records the failure)."""
    tenant = project.tenant
    roles = resolve_llm_roles(tenant)
    cfg = roles.get(ROLE)
    if not cfg:
        raise RuntimeError(
            f"No '{ROLE}' LLM role configured for this workspace — set it under "
            "Workspace Settings → LLM."
        )

    roster = _component_roster(tenant, project)
    root = _root_component(project)

    client = get_platform_client(project.platform_connection)
    # Route through the auth-method seam, scoping a GitHub App installation
    # token to this project's repository. PAT connections return the stored
    # token unchanged, so their behavior is identical.
    client.token = project.platform_connection.get_access_token(
        repositories=[project.full_path]
    )
    toolbox = _RepoToolbox(client, project.full_path, project.default_branch)
    agent = LLMAgent(
        model=cfg["model"],
        api_key=cfg.get("api_key"),
        base_url=cfg.get("base_url"),
        log=lambda m: logger.info("deps[%s]: %s", project.name, m),
    )

    result: DependencyResult = agent.run(
        toolbox=toolbox,
        system_prompt=_SYSTEM_PROMPT,
        instructions=_build_instructions(project, roster),
        response_model=DependencyResult,
    )
    logger.info(
        "deps[%s]: %d internal, %d infra, %d providers, %d consumers "
        "(%d tokens, %d calls, %d files read)",
        project.name,
        len(result.internal),
        len(result.infrastructure),
        len(result.external_providers),
        len(result.external_consumers),
        agent.usage["total_tokens"],
        agent.usage["calls"],
        len(toolbox.files_read),
    )

    # Evidence gate: an answer the model never grounded in the repository is a
    # guess, and a guess saved as ``ok`` silently replaces a correct map. Raise
    # before touching the edge tables so the previous map survives and the task
    # records a readable reason in deps_error.
    if toolbox.tree_size == 0:
        raise RuntimeError(
            "Repository listing came back empty — the connection cannot read this "
            "repository's files. Check the platform connection's access to the repo "
            "and the project's default branch. The previous map was kept."
        )
    if not toolbox.files_read:
        raise RuntimeError(
            "The model answered without reading any repository file, so the result "
            "was not saved and the previous map was kept. Check the LLM role's model "
            "and provider, then re-run the analysis."
        )

    # Resolve + persist atomically (replace this project's outgoing edges).
    component_deps = []
    seen_targets = set()
    for dep in result.internal:
        target_pk = _resolve_internal_target(dep.target, roster)
        if not target_pk or target_pk == root.pk or target_pk in seen_targets:
            if not target_pk:
                logger.info("deps[%s]: unresolved internal target %r", project.name, dep.target)
            continue
        seen_targets.add(target_pk)
        component_deps.append(
            ComponentDependency(
                tenant=tenant, source=root, target_id=target_pk, label=dep.label[:255]
            )
        )

    # Infrastructure (internal datastores/queues this service owns).
    infra = {}
    _VALID_KINDS = {"database", "cache", "queue", "storage", "other"}

    def _add_infra(name, kind, label=""):
        name = (name or "").strip()
        key = name.lower()
        if not name or key in infra or _resolve_internal_target(name, roster):
            return
        if kind not in _VALID_KINDS:
            kind = _infra_kind(name) or "other"
        infra[key] = InfrastructureComponent(
            tenant=tenant, component=root, name=name[:255], kind=kind,
            description=(label or "")[:255],
        )

    for d in result.infrastructure:
        _add_infra(d.name, d.kind, d.label)

    external_deps = []

    def _collect(deps, direction):
        seen = set()
        for dep in deps:
            name = (dep.name or "").strip()
            if not name:
                continue
            # The LLM sometimes lists workspace repos as "external" — those
            # belong to internal ComponentDependency, captured elsewhere.
            if _resolve_internal_target(name, roster):
                logger.info("deps[%s]: dropping workspace repo %r from external", project.name, name)
                continue
            # Backstop: a datastore/queue is internal infrastructure, never an
            # external service (only applies to things we depend on).
            if direction == ExternalDependency.Direction.OUTBOUND:
                if name.lower() in _GENERIC_CLOUD:
                    continue  # bare cloud provider — its services are infra
                ik = _infra_kind(name)
                if ik:
                    _add_infra(name, ik, dep.label)
                    continue
            key = canonical_key(name)  # collapse "Stripe" / "Stripe API"
            if key in seen:
                continue
            seen.add(key)
            external_deps.append(
                ExternalDependency(
                    tenant=tenant,
                    component=root,
                    name=name[:255],
                    direction=direction,
                    url=(dep.url or "")[:2048],
                    description=dep.label[:255],
                )
            )

    _collect(result.external_providers, ExternalDependency.Direction.OUTBOUND)
    _collect(result.external_consumers, ExternalDependency.Direction.INBOUND)
    infra_components = list(infra.values())

    # Inferred tech labels (deduped, capped); merged with GitHub languages at
    # render time.
    technologies = []
    seen_tech = set()
    for t in result.technologies:
        t = (t or "").strip()
        key = t.lower()
        if t and key not in seen_tech:
            seen_tech.add(key)
            technologies.append(t[:60])

    with transaction.atomic():
        ComponentDependency.objects.filter(tenant=tenant, source__project=project).delete()
        ExternalDependency.objects.filter(tenant=tenant, component__project=project).delete()
        InfrastructureComponent.objects.filter(tenant=tenant, component__project=project).delete()
        ComponentDependency.objects.bulk_create(component_deps, ignore_conflicts=True)
        ExternalDependency.objects.bulk_create(external_deps, ignore_conflicts=True)
        InfrastructureComponent.objects.bulk_create(infra_components, ignore_conflicts=True)
        root.technologies = technologies[:20]
        root.save(update_fields=["technologies", "updated_at"])
        project.deps_evidence = toolbox.files_read[:50]
        project.deps_status = Project.DepsStatus.OK
        project.deps_analyzed_at = timezone.now()
        project.deps_error = ""
        project.save(
            update_fields=[
                "deps_evidence",
                "deps_status",
                "deps_analyzed_at",
                "deps_error",
            ]
        )

    return result
