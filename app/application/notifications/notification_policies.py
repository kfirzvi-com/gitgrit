"""Notification policies: "whenever X happens, raise notification Y".

Each notification policy reacts to one domain event, decides whether it is
worth telling anyone, gathers the facts, builds the notification through its
named constructor on ``Notification`` (which holds the wording) and raises it.
It never decides who hears it; that is notification routing's job
(``notification_routing.py``). Workers publish the events and know nothing
about these listeners.
"""

from __future__ import annotations

from app.application.event_bus import subscribe
from app.application.notifications.service import raise_notification
from app.domain.events import DependencyInferenceFailed, StandardRunFinished
from app.domain.models import Notification, Project, StandardExecution

# ``triggered_by`` values written by the app itself (``standard_runs`` and
# ``subscribers``); anything else there is a webhook actor's username.
_APP_TRIGGERS = frozenset({"manual", "attached", "activated", "saved"})
_WEBHOOK_EVENTS = frozenset({"push", "pull_request"})


class CouldNotEvaluateNotificationPolicy:
    """Whenever a run could not be evaluated at all (the job itself failed, or
    every standard in it errored), raise "GitGrit could not evaluate"."""

    def handle(self, event: StandardRunFinished) -> None:
        if not could_not_evaluate(event):
            return
        project = _project(event)
        if project is None:
            return
        rows = _rows(event, project)
        errored = [r for r in rows if r.status == StandardExecution.Status.ERROR]
        first = errored[0] if errored else None
        raise_notification(
            Notification.could_not_evaluate(
                project=project,
                error=event.error or _row_error(first),
                execution_id=first.pk if first else None,
                execution_ids=event.execution_ids,
                trigger=_trigger(rows[0] if rows else None),
                triggered_by_user_ids=_triggered_by(event),
            )
        )


class StandardsFailingNotificationPolicy:
    """Whenever a run that could be evaluated left standards failing, raise
    one "N standards failed" for the run. The count and names are this run's
    failures; the score is the project's current overall score."""

    def handle(self, event: StandardRunFinished) -> None:
        if event.failed == 0 or could_not_evaluate(event):
            return
        project = _project(event)
        if project is None:
            return
        failed = [
            r for r in _rows(event, project, order="score")
            if r.status == StandardExecution.Status.FAILED
        ]
        # The event said "failed" but none of this run's rows are failed rows
        # (superseded, or another project's): a "0 standards failed" is noise.
        if not failed:
            return
        raise_notification(
            Notification.standards_failing(
                project=project,
                failed_names=[r.standard_name for r in failed],
                failed_standard_ids=[r.standard_id for r in failed],
                execution_ids=event.execution_ids,
                score=_overall_score(project),
                trigger=_trigger(failed[0]),
                triggered_by_user_ids=_triggered_by(event),
            )
        )


class GraphBrokeNotificationPolicy:
    """Whenever a dependency map that used to build fails to rebuild, raise
    "Dependency graph failed". A workspace whose map never built (no AI
    model, say) would fail on every push, so it is not told."""

    def handle(self, event: DependencyInferenceFailed) -> None:
        if not event.had_worked_before:
            return
        project = _project(event)
        if project is None:
            return
        raise_notification(Notification.graph_failed(project=project, error=event.error))


NOTIFICATION_POLICIES = (
    (StandardRunFinished, CouldNotEvaluateNotificationPolicy()),
    (StandardRunFinished, StandardsFailingNotificationPolicy()),
    (DependencyInferenceFailed, GraphBrokeNotificationPolicy()),
)


def register() -> None:
    for event_type, policy in NOTIFICATION_POLICIES:
        subscribe(event_type, policy.handle)


def could_not_evaluate(event: StandardRunFinished) -> bool:
    """The job failed, or every standard in the run errored."""
    all_errored = event.errored > 0 and event.passed == 0 and event.failed == 0
    return bool(event.error) or all_errored


# --- Facts the notification policies gather ----------------------------------------------


def _project(event):
    return Project.objects.filter(pk=event.project_id, tenant_id=event.tenant_id).first()


def _rows(event, project, order="created_at"):
    return list(
        StandardExecution.objects.filter(pk__in=event.execution_ids, project=project).order_by(order)
    )


def _row_error(row) -> str:
    """``run_standards`` stores the error text under details["error"]; the
    sandbox only sets the flag (``True``) and puts the traceback in
    ``message``."""
    if row is None:
        return ""
    stored = row.details.get("error")
    return stored if isinstance(stored, str) and stored else row.message


def _trigger(execution) -> str | None:
    """One short word for what started the check: ``push`` or
    ``pull_request`` for webhook runs, else how the app queued it
    (``manual``/``attached``/``activated``/``saved``), else the raw event
    type. None when nothing is known."""
    if execution is None:
        return None
    event_type = (execution.event_type or "").strip()
    if event_type in _WEBHOOK_EVENTS:
        return event_type
    triggered_by = (execution.triggered_by or "").strip()
    if triggered_by in _APP_TRIGGERS:
        return triggered_by
    return event_type or None


def _triggered_by(event) -> list[str]:
    """Users who started this run, in order, without repeats."""
    ids = StandardExecution.objects.filter(
        pk__in=event.execution_ids, triggered_by_user__isnull=False
    ).values_list("triggered_by_user_id", flat=True)
    return list(dict.fromkeys(str(u) for u in ids))


def _overall_score(project):
    from app.application.project_status_service import ProjectStatusService

    return ProjectStatusService().get_project_status(project.tenant, str(project.pk))[
        "overall_score"
    ]
