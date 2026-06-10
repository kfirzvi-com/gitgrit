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
