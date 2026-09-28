"""Turning a topology's names into workspace references.

The inference names other components loosely ("org/api", "api", "auth-service",
"org/mono/apps/api-gateway"); the roster is the set of components it may mean.
This module maps one to the other and applies the classification rules that
correct the most common model mistakes: a datastore filed as an external
service, a bare cloud provider, a workspace repo listed as external, the same
service spelled two ways.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.domain.architecture.naming import canonical_key
from app.domain.architecture.topology import (
    INFRA_KINDS,
    OUTBOUND,
    ExternalLink,
    InfrastructureResource,
    RepositoryTopology,
    safe_url,
)


@dataclass(frozen=True)
class RosterEntry:
    """One workspace component as the inference may refer to it.
    ``component_id`` is None for a sibling that is about to be created."""

    full_path: str
    path: str
    name: str
    component_id: object | None = None

    @property
    def is_root(self) -> bool:
        return self.path == ""

    @property
    def ref(self) -> str:
        return self.full_path if self.is_root else f"{self.full_path}#{self.path}"


def resolve_ref(
    target: str, roster: Iterable[RosterEntry], *, this_repo: str = "", strict: bool = False
) -> RosterEntry | None:
    """Best-effort mapping of a model-returned target onto one roster entry.

    Tried in order: exact ref (``repo`` or ``repo#path``); ``#path`` or a bare
    path naming a sibling in ``this_repo``; a bare repository (its root, or
    its only component); ``repo/path`` written with a slash; a unique
    component name; a repository's last path segment (its root component).

    ``strict`` (a hand-written ``.gitgrit.yml`` target) stops after the exact
    forms — exact ref, ``#path`` sibling, bare repository — and never guesses.
    """
    t = (target or "").strip().lower().rstrip("/")
    if not t:
        return None
    roster = list(roster)
    by_ref = {e.ref.lower(): e for e in roster}
    if t in by_ref:
        return by_ref[t]

    if this_repo and (t.startswith("#") or not strict):
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
    if strict:
        return None

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
    "cockroach": "database", "cockroachdb": "database", "rds": "database", "aurora": "database",
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
    """An infrastructure kind if the name is a known datastore/queue, else None.

    Terms match whole words ("Amazon RDS", "aws-s3", "sqlite3" — a version
    number may follow), never inside a word ("Rewards", "Sales3").
    """
    words = " ".join(re.findall(r"[a-z0-9]+", (name or "").lower()))
    for term, kind in INFRA_TERMS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}\d*(?![a-z0-9])", words):
            return kind
    return None


# --- Resolution of a whole topology ---------------------------------------------


@dataclass(frozen=True)
class ResolvedInternal:
    source_path: str
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
    topology: RepositoryTopology, roster: Iterable[RosterEntry], *, this_repo: str
) -> ResolvedTopology:
    """Resolve internal targets and clean externals/infrastructure.

    A ``.gitgrit.yml`` map (``source == "file"``) is kept as written: its
    targets must match exactly and the backstops for model mistakes (bare
    cloud providers, datastores filed as externals, workspace names, near
    duplicates) are skipped.
    """
    roster = list(roster)
    own_paths = {c.path for c in topology.components}
    as_written = topology.source == "file"

    internal: list[ResolvedInternal] = []
    unresolved: list[str] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for dep in topology.internal:
        if dep.source_path not in own_paths:
            continue
        entry = resolve_ref(dep.target_ref, roster, this_repo=this_repo, strict=as_written)
        if entry is None:
            unresolved.append(dep.target_ref)
            continue
        if entry.full_path.lower() == this_repo.lower() and entry.path == dep.source_path:
            continue  # self-loop
        key = (dep.source_path, entry.full_path.lower(), entry.path)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        internal.append(ResolvedInternal(dep.source_path, entry, dep.label[:255]))

    infra: dict[tuple[str, str], InfrastructureResource] = {}

    def add_infra(source_path: str, name: str, kind: str, label: str = "") -> None:
        name = (name or "").strip()
        key = (source_path, name.lower())
        if not name or key in infra:
            return
        if not as_written and resolve_ref(name, roster, this_repo=this_repo):
            return
        if kind not in INFRA_KINDS:
            kind = infra_kind(name) or "other"
        infra[key] = InfrastructureResource(
            source_path=source_path, name=name[:255], kind=kind, label=(label or "")[:255]
        )

    for res in topology.infrastructure:
        if res.source_path in own_paths:
            add_infra(res.source_path, res.name, res.kind, res.label)

    externals: list[ExternalLink] = []
    seen_ext: set[tuple[str, str, str]] = set()
    for ext in topology.externals:
        if ext.source_path not in own_paths:
            continue
        name = (ext.name or "").strip()
        if not name:
            continue
        if not as_written:
            # A workspace component listed as "external" belongs to internal edges.
            if resolve_ref(name, roster, this_repo=this_repo):
                continue
            if ext.direction == OUTBOUND:
                if name.lower() in GENERIC_CLOUD:
                    continue
                kind = infra_kind(name)
                if kind:
                    add_infra(ext.source_path, name, kind, ext.label)
                    continue
        dedupe = name.lower() if as_written else canonical_key(name)
        key = (ext.source_path, dedupe, ext.direction)
        if key in seen_ext:
            continue
        seen_ext.add(key)
        externals.append(
            ExternalLink(
                source_path=ext.source_path,
                name=name[:255],
                direction=ext.direction,
                url=safe_url(ext.url),
                label=(ext.label or "")[:255],
            )
        )

    return ResolvedTopology(
        internal=tuple(internal),
        externals=tuple(externals),
        infrastructure=tuple(infra.values()),
        unresolved=tuple(unresolved),
    )
