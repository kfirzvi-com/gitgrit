"""An inferred project topology, before it touches the database.

A ``ProjectTopology`` is what any inference adapter (LLM, fixture, future
model) must produce for one project: its dependencies on other workspace
projects, on external services, and on the infrastructure it owns, its tech
labels, and — for a whole-repository project — the apps, services and
libraries inside the repository worth suggesting as projects. Other projects
are addressed by *refs* (``org/repo`` or ``org/repo#path``), never by
database ids, so a topology can be produced offline, stored as a fixture, and
compared against a golden file.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable

from app.domain.projects import SuggestedProject

INFRA_KINDS = ("database", "cache", "queue", "storage", "other")
OUTBOUND = "outbound"  # the project depends on the external system
INBOUND = "inbound"  # the external system depends on the project

MAX_TECHNOLOGIES = 20
MAX_EVIDENCE_FILES = 50


@dataclass(frozen=True)
class InternalDependency:
    """The project depends on ``target_ref``, another workspace project named
    the way the roster names it: ``org/repo`` for a whole-repository project,
    ``org/repo#path`` for one inside a monorepo, ``#path`` for one in the same
    repository."""

    target_ref: str
    label: str = ""


@dataclass(frozen=True)
class ExternalLink:
    """A relationship between the project and a system outside the workspace."""

    name: str
    direction: str = OUTBOUND
    url: str = ""
    label: str = ""


@dataclass(frozen=True)
class InfrastructureResource:
    """A datastore/queue/cache/bucket the project owns and operates."""

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
class ProjectTopology:
    technologies: tuple[str, ...] = ()
    internal: tuple[InternalDependency, ...] = ()
    externals: tuple[ExternalLink, ...] = ()
    infrastructure: tuple[InfrastructureResource, ...] = ()
    suggestions: tuple[SuggestedProject, ...] = ()
    evidence: Evidence = field(default_factory=Evidence)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["suggestions"] = [s.to_dict() for s in self.suggestions]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> ProjectTopology:
        """Inverse of ``to_dict``; tolerant of missing optional sections so a
        hand-written fixture can stay short."""
        return cls(
            technologies=tuple(data.get("technologies", ())),
            internal=tuple(InternalDependency(**d) for d in data.get("internal", [])),
            externals=tuple(ExternalLink(**e) for e in data.get("externals", [])),
            infrastructure=tuple(InfrastructureResource(**i) for i in data.get("infrastructure", [])),
            suggestions=tuple(SuggestedProject.from_dict(s) for s in data.get("suggestions", [])),
            evidence=Evidence(
                tree_size=data.get("evidence", {}).get("tree_size"),
                files_read=tuple(data.get("evidence", {}).get("files_read", ())),
            ),
        )

    @classmethod
    def of_repository(cls, data: dict, root_path: str) -> ProjectTopology:
        """One project's slice of a whole-repository description (the demo
        fixtures and golden files): ``units`` (each a path inside the
        repository) and edges keyed by ``source_path``. The project at
        ``root_path`` gets that unit's edges and technologies; the
        whole-repository project also gets every other unit as a suggestion."""
        units = data.get("units") or data.get("components") or []
        own = next((u for u in units if (u.get("path") or "") == root_path), {})

        def mine(rows):
            return [r for r in rows if (r.get("source_path") or "") == root_path]

        return cls(
            technologies=tuple(own.get("technologies", ())),
            internal=tuple(
                InternalDependency(d["target_ref"], d.get("label", "")) for d in mine(data.get("internal", []))
            ),
            externals=tuple(
                ExternalLink(e["name"], e.get("direction", OUTBOUND), e.get("url", ""), e.get("label", ""))
                for e in mine(data.get("externals", []))
            ),
            infrastructure=tuple(
                InfrastructureResource(i["name"], i.get("kind", "other"), i.get("label", ""))
                for i in mine(data.get("infrastructure", []))
            ),
            suggestions=tuple(
                SuggestedProject.from_dict(u) for u in units if u.get("path")
            ) if not root_path else (),
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
