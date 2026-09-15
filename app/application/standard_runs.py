"""Queueing standard runs.

Running a standard means starting a sandboxed container per standard, which is
far too slow for an HTTP request: the Kamal proxy gives up on a request after
30s and GitHub stops waiting for a webhook delivery after 10s. So every trigger
— the Run / Run All buttons, the coverage-change subscribers (attach, save,
activate) and webhook deliveries — comes through here: the ``StandardExecution``
rows are created RUNNING so the project page shows them straight away, and the
``run_standards`` Procrastinate job (``app.tasks``) fills them in.

Dependency direction: views / webhooks / subscribers -> this module ->
``StandardEngine`` (matching, input config, one execution) -> sandbox. The
worker task imports the engine lazily; nothing here is imported by the engine.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from app.application.event_bus import publish
from app.application.standard_engine import StandardEngine, literal_ref
from app.domain.events import DomainEvent, RepositoryPushed
from app.domain.identity import resolve_user
from app.domain.models import Project, Standard, StandardExecution
from app.tasks import run_standards

logger = logging.getLogger(__name__)


# --- Stale runs ----------------------------------------------------------------
# A RUNNING row is a promise the worker will finish it. If the worker is down,
# the job was lost, or the row predates background runs, that promise is never
# kept: the project page would poll forever and — because manual runs skip
# standards that are "already running" — the Run button would stay disabled
# forever. So a RUNNING row older than the cutoff is treated as not running
# anywhere it matters, and the periodic sweep turns it into an ERROR row.


def stale_cutoff():
    return timezone.now() - timedelta(minutes=settings.STANDARD_RUN_STALE_MINUTES)


def in_flight(queryset):
    """The RUNNING executions of ``queryset`` the worker can still be expected
    to finish (younger than the stale cutoff)."""
    return queryset.filter(
        status=StandardExecution.Status.RUNNING, created_at__gte=stale_cutoff()
    )


STALE_MESSAGE = (
    "Run did not finish within {minutes} minutes. The background worker may "
    "be down or was restarted mid-run; check the worker, then run again."
)


def expire_stale_runs() -> int:
    """Mark RUNNING executions older than the cutoff as ERROR. Returns the
    number of rows changed. Called by the periodic ``expire_stale_standard_runs``
    job; safe to run at any time."""
    message = STALE_MESSAGE.format(minutes=settings.STANDARD_RUN_STALE_MINUTES)
    changed = StandardExecution.objects.filter(
        status=StandardExecution.Status.RUNNING, created_at__lt=stale_cutoff()
    ).update(
        status=StandardExecution.Status.ERROR,
        message=message,
        details={"error": message},
    )
    if changed:
        logger.warning("expired %d stale standard run(s)", changed)
    return changed


# --- Feedback ------------------------------------------------------------------


def queue_summary_message(
    queued: int, already_running: int, target: str, *, projects: int = 1
) -> str:
    """The one sentence every publish site flashes after queueing runs.
    ``target`` names where the runs landed: a project name, or "3 projects"
    (with ``projects`` saying how many, so the tail points at each page)."""
    where = "each project page" if projects > 1 else "the project page"
    return (
        f"Queued {queued} standard{'' if queued == 1 else 's'} on {target}"
        + (f", {already_running} already running" if already_running else "")
        + f". Results appear on {where} as they finish."
    )


# --- Enqueueing ----------------------------------------------------------------


def enqueue_run(
    project: Project,
    standards,
    *,
    event_type: str = "manual",
    triggered_by: str = "manual",
    user=None,
    ref: str | None = None,
    skip_running: bool = True,
) -> dict | None:
    """Queue ``standards`` to run on ``project`` in the background.

    ``ref`` is the branch or tag the sandbox reads the repository at, stored
    on each execution. Webhook runs pass the event's ref; ``None`` (manual and
    coverage-change runs, which have no event) reads at the branch each
    standard's Branch/Tag Filter names literally, else the default branch.

    With ``skip_running`` (manual and coverage-change runs), standards that
    already have an in-flight execution on this project are left alone and
    counted as ``already_running`` — re-queueing them would run the same
    check twice. Webhook runs pass ``False``: every event gets its own run.

    The rows and the job are written in one transaction, so a failed defer
    never leaves RUNNING rows nothing will finish. Returns the summary publish
    sites flash — counts, ``message`` and the queued ``executions`` — or None
    when there was nothing to do.
    """
    standards = list(standards)
    if not standards:
        return None

    running_standard_ids: set = set()
    if skip_running:
        running_standard_ids = set(
            in_flight(
                StandardExecution.objects.filter(project=project, standard__in=standards)
            ).values_list("standard_id", flat=True)
        )
    to_run = [s for s in standards if s.pk not in running_standard_ids]
    already_running = len(standards) - len(to_run)

    if not to_run and not already_running:
        return None

    def _ref(standard: Standard) -> str:
        if ref is not None:
            return ref
        return literal_ref((standard.criteria or {}).get("ref"))

    executions: list[StandardExecution] = []
    if to_run:
        # One savepoint for rows + job: a defer failure rolls the rows back
        # instead of aborting the caller's outer transaction (which would
        # poison every later write in it). The job lock serializes runs of
        # the same project so two never overlap.
        with transaction.atomic():
            executions = StandardExecution.objects.bulk_create(
                [
                    StandardExecution(
                        project=project,
                        standard=standard,
                        standard_name=standard.name,
                        event_type=event_type,
                        status=StandardExecution.Status.RUNNING,
                        triggered_by=triggered_by,
                        triggered_by_user=user,
                        ref=_ref(standard),
                    )
                    for standard in to_run
                ]
            )
            run_standards.configure(lock=f"standards:{project.pk}").defer(
                project_id=str(project.pk),
                execution_ids=[str(e.pk) for e in executions],
            )

    queued = len(executions)
    return {
        "queued": queued,
        "already_running": already_running,
        "project_id": str(project.pk),
        "message": queue_summary_message(queued, already_running, project.name),
        "executions": [
            {
                "execution_id": str(e.pk),
                "standard_id": str(e.standard_id),
                "standard_name": e.standard_name,
                "project_id": str(project.pk),
                "project_name": project.name,
                "status": e.status,
            }
            for e in executions
        ],
    }


def enqueue_manual_run(
    project: Project,
    standards,
    *,
    triggered_by: str = "manual",
    user=None,
) -> dict | None:
    """Queue the *runnable* subset of ``standards`` on ``project`` — enabled,
    non-draft, criteria-matching — the way Run All and the coverage-change
    subscribers do. None when nothing is eligible."""
    runnable = StandardEngine().runnable_standards(project, list(standards))
    if not runnable:
        return None
    return enqueue_run(project, runnable, triggered_by=triggered_by, user=user)


def enqueue_for_event(
    event: DomainEvent, installation_id: int | None = None
) -> list[dict]:
    """Queue the standards a webhook event triggers: one background job per
    matching project, one RUNNING execution per matching standard.

    Nothing runs inside the webhook request. Platforms stop waiting for a
    delivery after a few seconds (GitHub: 10s), and the sandbox takes longer
    than that per standard, so the request only records what will run and the
    ``run_standards`` job does the work. Returns one entry per queued
    execution (execution/standard/project identity) for the webhook response.
    """
    engine = StandardEngine()
    projects = engine.resolve_projects(event, installation_id=installation_id)

    if not projects.exists():
        logger.info(
            "No projects matched platform=%s external_id=%s",
            event.platform,
            event.external_project_id,
        )
        return []

    # Resolve the platform actor to a GitGrit user (once per event)
    actor_user = resolve_user(event.platform, event.actor)

    queued: list[dict] = []
    for project in projects:
        # A code push may change dependencies — trigger a graph refresh
        # (its own background job, additive to the standard runs below).
        if event.event_type == "push":
            publish(
                RepositoryPushed(
                    project_id=str(project.id),
                    tenant_id=str(project.tenant_id),
                    ref=event.ref,
                )
            )

        standards = engine.get_standards_for_project(
            project,
            event.event_type,
            ref=event.ref,
            target_ref=event.target_ref,
        )

        if not standards:
            logger.info(
                "No standards matched event_type=%s ref=%s target_ref=%s "
                "for project=%s (tenant=%s)",
                event.event_type,
                event.ref,
                event.target_ref,
                project.name,
                project.tenant.name,
            )
            continue

        logger.info(
            "Queueing %d standard(s) for project '%s' (event=%s)",
            len(standards),
            project.name,
            event.event_type,
        )
        # Every event gets its own run — a push while the previous push's run
        # is still in flight must not be dropped (skip_running=False); the
        # per-project job lock serializes them instead.
        summary = enqueue_run(
            project,
            standards,
            event_type=event.event_type,
            triggered_by=event.actor or "",
            user=actor_user,
            ref=event.ref or "",
            skip_running=False,
        )
        if summary:
            queued.extend(summary["executions"])

    return queued
