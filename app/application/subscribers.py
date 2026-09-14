"""Domain-event subscribers.

Graph feature: wires workspace events to background dependency inference. A
project's repo is the source of its dependencies, so the unit of work is
per-project; deferring with a per-project ``queueing_lock`` coalesces rapid
changes into one pending run, and ``lock`` serializes execution so two runs for
the same project never overlap. The defer happens inside the publisher's
transaction (Postgres queue), so it's atomic with the domain write.

Membership *removals* and deletions need no LLM run — the read-time stack-edge
derivation and FK cascade handle them.

Coverage-change runs: when the set of runnable standards effectively applying
to a project grows or changes — standards attached, a standard saved, a
standard activated — the delta is *queued* to run in the background (same
execution model as the Run button): RUNNING executions are created in the
publisher's request and the ``run_standards`` job fills them in. Handlers
return a summary dict so publish sites can flash feedback; the bus swallows
handler exceptions, so a failed enqueue never fails the mutation it reacted to.
"""
from __future__ import annotations

import logging

from django.db import transaction
from procrastinate.exceptions import AlreadyEnqueued

from app.application.event_bus import subscribe
from app.application.standard_runs import enqueue_manual_run, queue_summary_message
from app.domain.events import (
    ProjectAddedToStack,
    ProjectCreated,
    RepositoryPushed,
    StandardActivated,
    StandardsAttached,
    StandardSaved,
)
from app.tasks import infer_project_dependencies

logger = logging.getLogger(__name__)


def _enqueue_dependency_refresh(project_id: str) -> None:
    from app.domain.models import Project

    Project.objects.filter(pk=project_id).update(
        deps_status=Project.DepsStatus.PENDING
    )
    try:
        # Savepoint: a duplicate-job unique violation must not abort the
        # publisher's outer transaction (it would poison every later write in
        # that transaction with "current transaction is aborted").
        with transaction.atomic():
            infer_project_dependencies.configure(
                lock=f"project:{project_id}",
                queueing_lock=f"deps:{project_id}",
            ).defer(project_id=str(project_id))
    except AlreadyEnqueued:
        # A refresh for this project is already queued — coalesced.
        logger.debug("dependency refresh already queued for project %s", project_id)


def _on_project_event(event) -> None:
    _enqueue_dependency_refresh(event.project_id)


def _queue_on_project(project, standards, triggered_by) -> dict | None:
    """Queue the runnable subset of ``standards`` on ``project``; the enqueue
    summary, or None when nothing is eligible."""
    return enqueue_manual_run(project, standards, triggered_by=triggered_by)


def _summarize(per_project: list[dict]) -> dict | None:
    """Fold per-project enqueue counts into the feedback summary publish sites
    flash to the user and MCP tools return."""
    per_project = [c for c in per_project if c]
    if not per_project:
        return None
    queued = sum(c["queued"] for c in per_project)
    already_running = sum(c["already_running"] for c in per_project)
    projects = len(per_project)
    target = f"{projects} project{'' if projects == 1 else 's'}"
    return {
        "projects": projects,
        "queued": queued,
        "already_running": already_running,
        "message": queue_summary_message(
            queued, already_running, target, projects=projects
        ),
    }


def _on_standards_attached(event: StandardsAttached) -> dict | None:
    from app.domain.models import Project, Standard

    project = Project.objects.filter(
        pk=event.project_id, tenant_id=event.tenant_id
    ).first()
    if project is None:
        return None
    standards = list(
        Standard.objects.filter(pk__in=event.standard_ids, tenant_id=event.tenant_id)
    )
    counts = _queue_on_project(project, standards, triggered_by="attached")
    return _summarize([counts] if counts else [])


def _on_standard_changed(event: StandardSaved | StandardActivated) -> dict | None:
    """Saved and activated get the identical reaction: queue the standard to
    re-run on every project it's attached to."""
    from app.domain.models import Standard

    standard = (
        Standard.objects.filter(pk=event.standard_id, tenant_id=event.tenant_id)
        .prefetch_related("projects")
        .first()
    )
    if standard is None:
        return None
    triggered_by = "activated" if isinstance(event, StandardActivated) else "saved"
    per_project = [
        counts
        for project in standard.projects.all()
        if (counts := _queue_on_project(project, [standard], triggered_by=triggered_by))
    ]
    return _summarize(per_project)


def register() -> None:
    """Register subscribers. Called once from AppConfig.ready()."""
    subscribe(ProjectCreated, _on_project_event)
    subscribe(ProjectAddedToStack, _on_project_event)
    subscribe(RepositoryPushed, _on_project_event)
    subscribe(StandardsAttached, _on_standards_attached)
    subscribe(StandardSaved, _on_standard_changed)
    subscribe(StandardActivated, _on_standard_changed)
