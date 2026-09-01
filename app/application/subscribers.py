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
standard activated — the delta runs immediately, synchronously in the
publisher's request (same execution model as the Run button). Handlers return
a summary dict so publish sites can flash feedback; the bus swallows handler
exceptions, so a failed run never fails the mutation it reacted to.
"""
from __future__ import annotations

import logging

from procrastinate.exceptions import AlreadyEnqueued

from app.application.event_bus import subscribe
from app.application.standard_engine import StandardEngine
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
        infer_project_dependencies.configure(
            lock=f"project:{project_id}",
            queueing_lock=f"deps:{project_id}",
        ).defer(project_id=str(project_id))
    except AlreadyEnqueued:
        # A refresh for this project is already queued — coalesced.
        logger.debug("dependency refresh already queued for project %s", project_id)


def _on_project_event(event) -> None:
    _enqueue_dependency_refresh(event.project_id)


def _run_on_project(project, standards) -> dict | None:
    """Run the runnable subset of ``standards`` on ``project``; per-project
    counts, or None when nothing is eligible."""
    engine = StandardEngine()
    runnable = engine.runnable_standards(project, standards)
    if not runnable:
        return None
    results = engine.run_for_project(project, runnable)
    # Error takes precedence over passed, mirroring the engine's execution
    # statuses, so each result lands in exactly one bucket.
    passed = errors = 0
    for r in results:
        if r.get("details", {}).get("error"):
            errors += 1
        elif r.get("passed"):
            passed += 1
    return {"ran": len(results), "passed": passed, "errors": errors}


def _summarize(per_project: list[dict]) -> dict | None:
    """Fold per-project counts into the feedback summary publish sites flash
    to the user and MCP tools return."""
    if not per_project:
        return None
    ran = sum(c["ran"] for c in per_project)
    passed = sum(c["passed"] for c in per_project)
    errors = sum(c["errors"] for c in per_project)
    failed = ran - passed - errors
    projects = len(per_project)
    message = (
        f"Ran {ran} standard{'' if ran == 1 else 's'} on "
        f"{projects} project{'' if projects == 1 else 's'}: "
        f"{passed} passed, {failed} failed"
        + (f", {errors} errored" if errors else "")
        + "."
    )
    return {
        "projects": projects,
        "ran": ran,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "message": message,
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
    counts = _run_on_project(project, standards)
    return _summarize([counts] if counts else [])


def _on_standard_changed(event: StandardSaved | StandardActivated) -> dict | None:
    """Saved and activated get the identical reaction: re-run the standard on
    every project it's attached to."""
    from app.domain.models import Standard

    standard = (
        Standard.objects.filter(pk=event.standard_id, tenant_id=event.tenant_id)
        .prefetch_related("projects")
        .first()
    )
    if standard is None:
        return None
    per_project = [
        counts
        for project in standard.projects.all()
        if (counts := _run_on_project(project, [standard]))
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
