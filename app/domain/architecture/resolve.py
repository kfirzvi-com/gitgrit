"""Turning a topology's names into workspace references.

The inference names other projects loosely ("org/api", "api", "auth-service",
"org/mono/apps/api-gateway"); the roster is the set of projects it may mean.
This module maps one to the other and applies the classification rules that
correct the most common model mistakes: a datastore filed as an external
service, a bare cloud provider, a workspace repo listed as external, the same
service spelled two ways.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain.architecture.naming import canonical_key
from app.domain.architecture.topology import (
    INFRA_KINDS,
    OUTBOUND,
    ExternalLink,
    InfrastructureResource,
    ProjectTopology,
)


@dataclass(frozen=True)
class RosterEntry:
    """One workspace project as the inference may refer to it: its
    repository (``full_path``), where it starts inside it (``path``, "" for
    the whole repository) and its name."""

    full_path: str
    path: str
    name: str
    project_id: object | None = None

    @property
    def is_root(self) -> bool:
        return self.path == ""

    @property
    def ref(self) -> str:
        return self.full_path if self.is_root else f"{self.full_path}#{self.path}"


def resolve_ref(target: str, roster: Iterable[RosterEntry], *, this_repo: str = "") -> RosterEntry | None:
    """Best-effort mapping of a model-returned target onto one roster entry.

    Tried in order: exact ref (``repo`` or ``repo#path``); ``#path`` or a bare
    path naming a project in ``this_repo``; a bare repository (its
    whole-repository project, or its only one); ``repo/path`` written with a
    slash; a unique project name; a repository's last path segment (its
    whole-repository project).
    """
    t = (target or "").strip().lower().rstrip("/")
    if not t:
        return None
    roster = list(roster)
    by_ref = {e.ref.lower(): e for e in roster}
    if t in by_ref:
        return by_ref[t]

    if this_repo:
        sibling_path = t[1:] if t.startswith("#") else t
        for e in roster:
            if e.full_path.lower() == this_repo.lower() and e.path.lower() == sibling_path:
                return e
    if t.startswith("#"):
        return None  # ``#path`` only ever names a sibling; never guess further

    by_repo: dict[str, list[RosterEntry]] = {}
    for e in roster:
        by_repo.setdefault(e.full_path.lower(), []).append(e)
    if t in by_repo:
        entries = by_repo[t]
        roots = [e for e in entries if e.is_root]
        if roots:
            return roots[0]
        if len(entries) == 1:
            return entries[0]

    for e in roster:
        if e.path and t == f"{e.full_path}/{e.path}".lower():
            return e

    by_name: dict[str, list[RosterEntry]] = {}
    for e in roster:
        by_name.setdefault(e.name.lower(), []).append(e)
    last = t.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    for key in (t, last):
        entries = by_name.get(key)
        if entries and len(entries) == 1:
            return entries[0]

    for e in roster:
        if e.is_root and e.full_path.lower().rsplit("/", 1)[-1] == last:
            return e
    return None


# --- Classification backstops ----------------------------------------------------

# Common self-operated datastores/queues/storage. If the model files one of
# these as an external service, it is reclassified as infrastructure.
INFRA_TERMS = {
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
GENERIC_CLOUD = {
    "aws", "amazon web services", "amazon", "gcp", "google cloud",
    "google cloud platform", "azure", "microsoft azure",
}


def infra_kind(name: str) -> str | None:
    """An infrastructure kind if the name is a known datastore/queue, else None."""
    n = (name or "").lower()
    for term, kind in INFRA_TERMS.items():
        if term in n:
            return kind
    return None


# --- Resolution of a whole topology ---------------------------------------------


@dataclass(frozen=True)
class ResolvedInternal:
    target: RosterEntry
    label: str


@dataclass(frozen=True)
class ResolvedTopology:
    """A topology whose internal targets point at roster entries and whose
    externals/infrastructure have been cleaned. ``unresolved`` lists internal
    targets nothing in the roster matched (logged, not stored)."""

    internal: tuple[ResolvedInternal, ...]
    externals: tuple[ExternalLink, ...]
    infrastructure: tuple[InfrastructureResource, ...]
    unresolved: tuple[str, ...]


def resolve_topology(
    topology: ProjectTopology, roster: Iterable[RosterEntry], *, this_repo: str, this_path: str = ""
) -> ResolvedTopology:
    """Resolve the project's internal targets against ``roster`` and clean its
    externals and infrastructure. ``this_repo`` / ``this_path`` name the
    project itself: an edge back to it is dropped, and ``#path`` targets name
    projects of the same repository."""
    roster = list(roster)

    def is_self(entry: RosterEntry) -> bool:
        return entry.full_path.lower() == this_repo.lower() and entry.path == this_path

    internal: list[ResolvedInternal] = []
    unresolved: list[str] = []
    seen_edges: set[tuple[str, str]] = set()
    for dep in topology.internal:
        entry = resolve_ref(dep.target_ref, roster, this_repo=this_repo)
        if entry is None:
            unresolved.append(dep.target_ref)
            continue
        if is_self(entry):
            continue  # self-loop
        key = (entry.full_path.lower(), entry.path)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        internal.append(ResolvedInternal(entry, dep.label[:255]))

    infra: dict[str, InfrastructureResource] = {}

    def add_infra(name: str, kind: str, label: str = "") -> None:
        name = (name or "").strip()
        key = name.lower()
        if not name or key in infra or resolve_ref(name, roster, this_repo=this_repo):
            return
        if kind not in INFRA_KINDS:
            kind = infra_kind(name) or "other"
        infra[key] = InfrastructureResource(name=name[:255], kind=kind, label=(label or "")[:255])

    for res in topology.infrastructure:
        add_infra(res.name, res.kind, res.label)

    externals: list[ExternalLink] = []
    seen_ext: set[tuple[str, str]] = set()
    for ext in topology.externals:
        name = (ext.name or "").strip()
        if not name:
            continue
        # A workspace project listed as "external" belongs to internal edges.
        if resolve_ref(name, roster, this_repo=this_repo):
            continue
        if ext.direction == OUTBOUND:
            if name.lower() in GENERIC_CLOUD:
                continue
            kind = infra_kind(name)
            if kind:
                add_infra(name, kind, ext.label)
                continue
        key = (canonical_key(name), ext.direction)
        if key in seen_ext:
            continue
        seen_ext.add(key)
        externals.append(
            ExternalLink(
                name=name[:255],
                direction=ext.direction,
                url=(ext.url or "")[:2048],
                label=(ext.label or "")[:255],
            )
        )

    return ResolvedTopology(
        internal=tuple(internal),
        externals=tuple(externals),
        infrastructure=tuple(infra.values()),
        unresolved=tuple(unresolved),
    )
