from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DomainEvent:
    event_type: str  # "push", "merge_request", etc.
    platform: str  # "github" | "gitlab"
    external_project_id: str  # platform's project/repo ID as string
    ref: str | None = None
    actor: str | None = None
    raw_payload: dict = field(default_factory=dict)


# --- Workspace domain events -------------------------------------------------
# Raised by application services when stacks/projects change; subscribers
# (see app.application.subscribers) react — e.g. enqueue dependency inference.
# Carry ids (not ORM objects) so they stay serializable and layer-clean.


@dataclass(frozen=True)
class StackCreated:
    stack_id: str
    tenant_id: str


@dataclass(frozen=True)
class ProjectCreated:
    project_id: str
    tenant_id: str


@dataclass(frozen=True)
class ProjectDeleted:
    project_id: str
    tenant_id: str


@dataclass(frozen=True)
class ProjectAddedToStack:
    project_id: str
    stack_id: str
    tenant_id: str


@dataclass(frozen=True)
class ProjectRemovedFromStack:
    project_id: str
    stack_id: str
    tenant_id: str


@dataclass(frozen=True)
class RepositoryPushed:
    project_id: str
    tenant_id: str
    ref: str | None = None


# --- Coverage-change events ----------------------------------------------------
# A standard's *coverage* changes when its association or definition does:
# attached to a project, saved, or activated. Subscribers run the affected
# (project, standard) delta immediately — see app.application.subscribers.
# Contract: each event has exactly one result-returning subscriber (the
# coverage runner), so publish sites read the run summary as ``results[0]``.


@dataclass(frozen=True)
class StandardsAttached:
    project_id: str
    tenant_id: str
    standard_ids: tuple[str, ...]  # only the newly attached, runnable ones


@dataclass(frozen=True)
class StandardSaved:
    standard_id: str
    tenant_id: str


@dataclass(frozen=True)
class StandardActivated:
    standard_id: str
    tenant_id: str
