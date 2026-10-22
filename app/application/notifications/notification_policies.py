"""Notification policies: "whenever X happens, raise notification Y".

Each notification policy reacts to one domain event, decides whether it is
worth telling anyone (the rules live in ``app.domain.notifications.
notification_rules``), gathers the facts, builds the notification through its
named constructor on ``Notification`` (which holds the wording) and raises it.
It never decides who hears it; that is notification routing's job
(``notification_routing.py``). Workers publish the events and know nothing
about these listeners.
"""

from __future__ import annotations

from app.application.event_bus import subscribe
from app.application.notifications.service import raise_notification
from app.domain.score_representation import ScoreHealth
from app.domain.events import (
    DependencyInferenceFailed,
    MemberJoined,
    MemberRemoved,
    MemberRoleChanged,
    ProjectCreated,
    ProjectDeleted,
    StandardActivated,
    StandardRunFinished,
    StandardRunsTimedOut,
    StandardSaved,
)
from app.domain.models import Notification, Project, Standard, StandardExecution, User
from app.domain.notifications import notification_rules

# ``triggered_by`` values written by the app itself (``standard_runs`` and
# ``subscribers``); anything else there is a webhook actor's username.
_APP_TRIGGERS = frozenset({"manual", "attached", "activated", "saved"})
_WEBHOOK_EVENTS = frozenset({"push", "pull_request"})


# --- Runs -------------------------------------------------------------------


class CouldNotEvaluateNotificationPolicy:
    """Whenever a run could not be evaluated at all (the job itself failed, or
    every standard in it errored), raise "GitGrit could not evaluate" — or
    "Git connection broken" when the project's connection no longer works,
    since that is the cause and the fix is in workspace settings."""

    def handle(self, event: StandardRunFinished) -> None:
        if not notification_rules.could_not_evaluate(event):
            return
        project = _project(event)
        if project is None:
            return
        rows = _rows(event, project)
        errored = [r for r in rows if r.status == StandardExecution.Status.ERROR]
        first = errored[0] if errored else None
        error = event.error or _row_error(first)
        trigger = _trigger(rows[0] if rows else None)
        triggered_by = _triggered_by(event)
        if notification_rules.looks_like_auth_failure(error) and not _connection_works(project):
            raise_notification(
                Notification.connection_broken(
                    project=project,
                    connection=project.platform_connection,
                    execution_ids=event.execution_ids,
                    trigger=trigger,
                    triggered_by_user_ids=triggered_by,
                )
            )
            return
        raise_notification(
            Notification.could_not_evaluate(
                project=project,
                error=error,
                execution_id=first.pk if first else None,
                execution_ids=event.execution_ids,
                trigger=trigger,
                triggered_by_user_ids=triggered_by,
            )
        )


class StandardsFailingNotificationPolicy:
    """Whenever a run that could be evaluated left standards failing, raise
    one "N standards failed" for the run. The count and names are this run's
    failures; the score is the project's current overall score."""

    def handle(self, event: StandardRunFinished) -> None:
        if not notification_rules.standards_failing(event):
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


class ProjectFailedNotificationPolicy:
    """Whenever a run fails a project (a Required standard failed or could
    not run on its newest commit), raise "Project failed"."""

    def handle(self, event: StandardRunFinished) -> None:
        if notification_rules.could_not_evaluate(event):
            return
        project = _project(event)
        if project is None:
            return
        before = _project_health(project, excluding=event.execution_ids)
        after = _project_health(project)
        if not notification_rules.became_failed(before, after):
            return
        rows = _rows(event, project)
        raise_notification(
            Notification.project_failed(
                project=project,
                reason=_project_status(project)["reason"],
                execution_ids=event.execution_ids,
                trigger=_trigger(rows[0] if rows else None),
                triggered_by_user_ids=_triggered_by(event),
            )
        )


class RunsTimedOutNotificationPolicy:
    """Whenever runs nobody finished are expired, raise "N standard runs
    timed out" for their project."""

    def handle(self, event: StandardRunsTimedOut) -> None:
        project = _project(event)
        if project is None:
            return
        raise_notification(
            Notification.runs_timed_out(
                project=project,
                execution_ids=event.execution_ids,
                triggered_by_user_ids=_triggered_by(event),
            )
        )


# --- Dependency map -----------------------------------------------------------


class GraphBrokeNotificationPolicy:
    """Whenever a dependency map that used to build fails to rebuild for a
    reason other than the AI provider, raise "Dependency graph failed"."""

    def handle(self, event: DependencyInferenceFailed) -> None:
        if not notification_rules.graph_broke(event):
            return
        project = _project(event)
        if project is None:
            return
        raise_notification(Notification.graph_failed(project=project, error=event.error))


class AIProviderFailedNotificationPolicy:
    """Whenever the workspace's AI provider refuses GitGrit (bad key, no
    credit, no access to the model), raise "AI provider refused GitGrit"."""

    def handle(self, event: DependencyInferenceFailed) -> None:
        if not notification_rules.ai_provider_refused(event):
            return
        project = _project(event)
        if project is None:
            return
        raise_notification(Notification.ai_provider_failed(project=project, error=event.error))


# --- Workspace changes --------------------------------------------------------


class ProjectAddedNotificationPolicy:
    """Whenever someone connects a project, tell the other admins."""

    def handle(self, event: ProjectCreated) -> None:
        project = _project(event)
        if project is None:
            return
        raise_notification(Notification.project_added(project=project, actor=_user(event.user_id)))


class ProjectRemovedNotificationPolicy:
    """Whenever someone removes a project, tell the other admins."""

    def handle(self, event: ProjectDeleted) -> None:
        raise_notification(
            Notification.project_removed(
                tenant_id=event.tenant_id,
                project_name=event.project_name or "A project",
                actor=_user(event.user_id),
            )
        )


class MemberJoinedNotificationPolicy:
    """Whenever someone is added to the workspace, tell the other admins."""

    def handle(self, event: MemberJoined) -> None:
        member = _user(event.user_id)
        if member is None:
            return
        raise_notification(
            Notification.member_joined(
                tenant_id=event.tenant_id,
                member=member,
                role=event.role,
                actor=_user(event.added_by_user_id),
            )
        )


class MemberRemovedNotificationPolicy:
    """Whenever someone leaves or is removed from the workspace, tell the
    other admins."""

    def handle(self, event: MemberRemoved) -> None:
        member = _user(event.user_id)
        if member is None:
            return
        raise_notification(
            Notification.member_removed(
                tenant_id=event.tenant_id, member=member, actor=_user(event.removed_by_user_id)
            )
        )


class MemberRoleChangedNotificationPolicy:
    """Whenever a member's role changes, tell the admins and that member."""

    def handle(self, event: MemberRoleChanged) -> None:
        member = _user(event.user_id)
        if member is None:
            return
        raise_notification(
            Notification.member_role_changed(
                tenant_id=event.tenant_id,
                member=member,
                old_role=event.old_role,
                new_role=event.new_role,
                actor=_user(event.changed_by_user_id),
            )
        )


class StandardChangedNotificationPolicy:
    """Whenever a runnable standard is saved or switched on, tell the other
    admins: it runs on its projects again, so scores may move."""

    def handle(self, event: StandardSaved | StandardActivated) -> None:
        standard = Standard.objects.filter(pk=event.standard_id, tenant_id=event.tenant_id).first()
        if standard is None:
            return
        raise_notification(
            Notification.standard_changed(
                standard=standard,
                actor=_user(event.user_id),
                activated=isinstance(event, StandardActivated),
            )
        )


NOTIFICATION_POLICIES = (
    (StandardRunFinished, CouldNotEvaluateNotificationPolicy()),
    (StandardRunFinished, StandardsFailingNotificationPolicy()),
    (StandardRunFinished, ProjectFailedNotificationPolicy()),
    (StandardRunsTimedOut, RunsTimedOutNotificationPolicy()),
    (DependencyInferenceFailed, GraphBrokeNotificationPolicy()),
    (DependencyInferenceFailed, AIProviderFailedNotificationPolicy()),
    (ProjectCreated, ProjectAddedNotificationPolicy()),
    (ProjectDeleted, ProjectRemovedNotificationPolicy()),
    (MemberJoined, MemberJoinedNotificationPolicy()),
    (MemberRemoved, MemberRemovedNotificationPolicy()),
    (MemberRoleChanged, MemberRoleChangedNotificationPolicy()),
    (StandardSaved, StandardChangedNotificationPolicy()),
    (StandardActivated, StandardChangedNotificationPolicy()),
)


def register() -> None:
    for event_type, policy in NOTIFICATION_POLICIES:
        subscribe(event_type, policy.handle)


# --- Facts the notification policies gather --------------------------------


def _project(event):
    return Project.objects.filter(pk=event.project_id, tenant_id=event.tenant_id).first()


def _user(user_id):
    return User.objects.filter(pk=user_id).first() if user_id else None


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


def _project_status(project, excluding=()):
    from app.application.project_status_service import ProjectStatusService

    return ProjectStatusService().get_project_status(
        project.tenant, str(project.pk), exclude_execution_ids=excluding
    )


def _overall_score(project, excluding=()):
    return _project_status(project, excluding)["overall_score"]


def _project_health(project, excluding=()):
    """The project's health (``ScoreHealth``): failed when a Required
    standard failed its newest scored commit."""
    status = _project_status(project, excluding)
    return ScoreHealth.tone(status["overall_score"], failed=status["score_failed"])


def _connection_works(project) -> bool:
    """Ask the platform whether the project's connection still works. Any
    doubt (no connection, a network error) counts as working, so a hiccup is
    never reported as a broken connection."""
    from app.infrastructure.platform_client import get_platform_client

    connection = project.platform_connection
    if connection is None:
        return True
    try:
        return get_platform_client(connection).test_token()
    except Exception:
        return True
