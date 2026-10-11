from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DomainEvent:
    event_type: str  # "push", "pull_request", etc.
    platform: str  # "github" | "gitlab"
    external_project_id: str  # platform's project/repo ID as string
    # The branch or tag the run reads the repository at: the pushed ref, or a
    # pull request's source branch.
    ref: str | None = None
    # A pull request's target branch; None for other events. The Branch/Tag
    # Filter matches this when present, else ``ref``.
    target_ref: str | None = None
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
    user_id: str | None = None  # who connected it


@dataclass(frozen=True)
class ProjectDeleted:
    project_id: str
    tenant_id: str
    project_name: str = ""  # the row is gone by the time listeners run
    user_id: str | None = None  # who removed it


@dataclass(frozen=True)
class ComponentAddedToStack:
    """A component joined a stack. Carries ``project_id`` because dependency
    inference runs per repository, not per component."""

    component_id: str
    project_id: str
    stack_id: str
    tenant_id: str


@dataclass(frozen=True)
class ComponentRemovedFromStack:
    component_id: str
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
# attached to a project, saved, or activated. Subscribers *queue* the affected
# (project, standard) delta to run in the background — see
# app.application.subscribers.
# Contract: each event has exactly one result-returning subscriber (the
# coverage runner), so publish sites read the enqueue summary as ``results[0]``.


@dataclass(frozen=True)
class StandardsAttached:
    project_id: str
    tenant_id: str
    standard_ids: tuple[str, ...]  # only the newly attached, runnable ones


@dataclass(frozen=True)
class StandardSaved:
    standard_id: str
    tenant_id: str
    user_id: str | None = None  # who saved it


@dataclass(frozen=True)
class StandardActivated:
    standard_id: str
    tenant_id: str
    user_id: str | None = None  # who activated it


# --- Run outcome events --------------------------------------------------------


@dataclass(frozen=True)
class StandardRunFinished:
    """Published by ``run_standards`` after a run, whatever its outcome.

    ``error`` is set only when the job itself blew up (token fetch, config
    build) and every remaining row was marked ERROR. Workers publish it and
    know nothing about who listens.
    """

    project_id: str
    tenant_id: str
    execution_ids: tuple[str, ...]
    passed: int
    failed: int
    errored: int
    error: str = ""


@dataclass(frozen=True)
class DependencyInferenceFailed:
    """Published by ``infer_project_dependencies`` once its in-process retries
    are exhausted.

    ``had_worked_before`` says whether this project had a map before this run,
    so listeners can stay quiet for workspaces where the graph has never
    worked (for example, no AI model configured).
    """

    project_id: str
    tenant_id: str
    error: str
    had_worked_before: bool
    # HTTP status of the AI provider's error, when the failure was one (401
    # bad key, 402/403 no credit or no access); None otherwise.
    provider_status: int | None = None


@dataclass(frozen=True)
class StandardRunsTimedOut:
    """Published by ``expire_stale_runs`` for each project whose RUNNING
    executions nobody finished in time and were marked ERROR."""

    project_id: str
    tenant_id: str
    execution_ids: tuple[str, ...]


# --- Workspace membership events -------------------------------------------------


@dataclass(frozen=True)
class MemberJoined:
    """Someone was added to a workspace (not its creator)."""

    tenant_id: str
    user_id: str
    role: str
    added_by_user_id: str | None = None


@dataclass(frozen=True)
class MemberRemoved:
    """Someone left a workspace or was removed from it. ``removed_by_user_id``
    is the member themselves when they left."""

    tenant_id: str
    user_id: str
    removed_by_user_id: str | None = None


@dataclass(frozen=True)
class MemberRoleChanged:
    """A member's role changed. Nothing publishes this yet: the app has no
    way to change a role. It is here so the notification is ready when one
    lands."""

    tenant_id: str
    user_id: str
    old_role: str
    new_role: str
    changed_by_user_id: str | None = None
