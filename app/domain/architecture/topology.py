"""An inferred repository topology, before it touches the database.

A ``RepositoryTopology`` is what any inference adapter (LLM, fixture, future
model) must produce for one repository: the components it contains and, per
component, its dependencies on other workspace components, on external
services, and on the infrastructure it owns. Everything is addressed by
*paths* (for this repository's components) and *refs* (for other workspace
components), never by database ids, so a topology can be produced offline,
stored as a fixture, and compared against a golden file.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Iterable

COMPONENT_KINDS = ("service", "frontend", "library", "job", "infra", "other")
INFRA_KINDS = ("database", "cache", "queue", "storage", "other")
OUTBOUND = "outbound"  # the component depends on the external system
INBOUND = "inbound"  # the external system depends on the component

MAX_COMPONENTS = 25
MAX_TECHNOLOGIES = 20
MAX_EVIDENCE_FILES = 50


@dataclass(frozen=True)
class ComponentDecl:
    """A deployable unit inside the repository. ``path`` is repository-relative
    and normalised (no leading/trailing slash); ``""`` is the repository root."""

    path: str
    name: str
    kind: str = "other"
    description: str = ""
    technologies: tuple[str, ...] = ()


@dataclass(frozen=True)
class InternalDependency:
    """``source_path`` (a component of this repo) depends on ``target_ref``,
    another workspace component named the way the roster names it:
    ``org/repo`` for a repository's root component, ``org/repo#path`` for a
    component inside a monorepo, ``#path`` for a sibling in this repository."""

    source_path: str
    target_ref: str
    label: str = ""


@dataclass(frozen=True)
class ExternalLink:
    """A relationship between a component and a system outside the workspace."""

    source_path: str
    name: str
    direction: str = OUTBOUND
    url: str = ""
    label: str = ""


@dataclass(frozen=True)
class InfrastructureResource:
    """A datastore/queue/cache/bucket a component owns and operates."""

    source_path: str
    name: str
    kind: str = "other"
    label: str = ""


@dataclass(frozen=True)
class Evidence:
    """What the inference actually looked at. ``tree_size`` is None when the
    repository was never listed; ``files_read`` is in read order."""

    tree_size: int | None = None
    files_read: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepositoryTopology:
    components: tuple[ComponentDecl, ...]
    internal: tuple[InternalDependency, ...] = ()
    externals: tuple[ExternalLink, ...] = ()
    infrastructure: tuple[InfrastructureResource, ...] = ()
    evidence: Evidence = field(default_factory=Evidence)

    @property
    def is_monorepo(self) -> bool:
        return len(self.components) > 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RepositoryTopology":
        """Inverse of ``to_dict``; tolerant of missing optional sections so a
        hand-written fixture can stay short."""
        return cls(
            components=tuple(
                ComponentDecl(**{**c, "technologies": tuple(c.get("technologies", ()))})
                for c in data.get("components", [])
            ),
            internal=tuple(InternalDependency(**d) for d in data.get("internal", [])),
            externals=tuple(ExternalLink(**e) for e in data.get("externals", [])),
            infrastructure=tuple(
                InfrastructureResource(**i) for i in data.get("infrastructure", [])
            ),
            evidence=Evidence(
                tree_size=data.get("evidence", {}).get("tree_size"),
                files_read=tuple(data.get("evidence", {}).get("files_read", ())),
            ),
        )


# --- Paths -------------------------------------------------------------------


def clean_path(path) -> str:
    """Normalise a model-supplied path: strip whitespace, backslashes, leading
    './' and surrounding slashes. '', '.', './' and '/' all become ''."""
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.strip("/")
    return "" if p == "." else p


def clean_technologies(values: Iterable[str], limit: int = MAX_TECHNOLOGIES) -> tuple[str, ...]:
    """Dedupe case-insensitively, keep first-seen order and spelling, cap."""
    seen: set[str] = set()
    out: list[str] = []
    for t in values or ():
        t = (t or "").strip()[:60]
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            out.append(t)
    return tuple(out[:limit])


def normalise_components(
    decls: Iterable[ComponentDecl],
    tree: Iterable[str],
    project_name: str,
    *,
    limit: int = MAX_COMPONENTS,
) -> tuple[ComponentDecl, ...]:
    """Turn a model's component list into the set we are willing to store.

    * paths are cleaned; a path with no file under it in the tree is dropped
      (the model named a directory that does not exist);
    * duplicates by path collapse to the first occurrence;
    * a missing name falls back to the last path segment; the root component
      is always named after the project;
    * an unknown ``kind`` becomes ``other``;
    * **exactly one surviving component is forced to the root** — a
      single-unit repository is always "the repository", whatever
      sub-directory the model pointed at — and no survivors means the root;
    * at most ``limit`` components, in the order the model gave them.

    The root, when present, sorts first so callers can rely on
    ``components[0]`` for it in a root-only result.
    """
    files = list(tree)
    dirs: set[str] = set()
    for f in files:
        parts = f.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))

    out: list[ComponentDecl] = []
    seen: set[str] = set()
    for decl in decls:
        path = clean_path(decl.path)
        if path and path not in dirs:
            continue
        if path in seen:
            continue
        seen.add(path)
        name = (decl.name or "").strip() or (path.rsplit("/", 1)[-1] if path else project_name)
        if not path:
            name = project_name
        kind = decl.kind if decl.kind in COMPONENT_KINDS else "other"
        out.append(
            replace(
                decl,
                path=path,
                name=name[:255],
                kind=kind,
                description=(decl.description or "")[:2000],
                technologies=clean_technologies(decl.technologies),
            )
        )
        if len(out) >= limit:
            break

    if not out:
        return (ComponentDecl(path="", name=project_name),)
    if len(out) == 1 and out[0].path:
        only = out[0]
        return (replace(only, path="", name=project_name),)
    out.sort(key=lambda d: (d.path != "", d.path))
    return tuple(out)


# --- Evidence gate -------------------------------------------------------------


class UngroundedTopology(RuntimeError):
    """The inference never looked at the repository, so its answer is a guess
    and must not replace the previous map."""


def check_evidence(evidence: Evidence) -> None:
    """Refuse an answer that was not grounded in the repository.

    A model that lists nothing (empty tree) or reads nothing has no basis for
    its result; saving it would silently replace a correct map with a guess.
    """
    if evidence.tree_size == 0:
        raise UngroundedTopology(
            "Repository listing came back empty — the connection cannot read this "
            "repository's files. Check the platform connection's access to the repo "
            "and the project's default branch. The previous map was kept."
        )
    if not evidence.files_read:
        raise UngroundedTopology(
            "The model answered without reading any repository file, so the result "
            "was not saved and the previous map was kept. Check the LLM role's model "
            "and provider, then re-run the analysis."
        )
