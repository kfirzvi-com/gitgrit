"""Sources: translators from domain events to notices.

A source turns a fact into a ``Notice`` and hands it to ``notify()``. It never
decides the audience; the rule table in ``router.py`` does. A finished run
yields ``run.failed`` (could not evaluate) or ``standards.failing``; a
dependency graph that gave up building yields ``graph.failed``. Every kind
goes to the whole team (see ``router.py``); the run's trigger is added on top.

Titles do not name the project: the inbox shows ``context["project_name"]``
(and the score, when there is one) in its own column next to the notice.
"""

from __future__ import annotations

from django.urls import reverse

from app.application.event_bus import subscribe
from app.application.notifications import notify
from app.domain.events import DependencyInferenceFailed, StandardRunFinished
from app.domain.notifications import Notice, Severity

_BODY_MAX = 200


_TRACEBACK = "Traceback (most recent call last):"

# ``triggered_by`` values written by the app itself (``standard_runs`` and
# ``subscribers``); anything else there is a webhook actor's username.
_APP_TRIGGERS = frozenset({"manual", "attached", "activated", "saved"})
_WEBHOOK_EVENTS = frozenset({"push", "pull_request"})


def _first_line(text: str) -> str:
    """One line of body text. A traceback's useful line is its last one
    (the exception); any other text is summarized by its first line."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[-1] if any(_TRACEBACK in line for line in lines) else lines[0]
    return line[:_BODY_MAX]


def _trigger(execution) -> str | None:
    """One short machine word for what started the check: ``push`` or
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


def _outcome(event: StandardRunFinished) -> str | None:
    """Which notice a finished run earns; "could not evaluate" outranks failing."""
    all_errored = event.errored > 0 and event.passed == 0 and event.failed == 0
    if event.error or all_errored:
        return "run.failed"
    if event.failed > 0:
        return "standards.failing"
    return None


def _mentioned(event: StandardRunFinished) -> tuple[str, ...]:
    """Users who triggered this run, so the router can tell them directly."""
    from app.domain.models import StandardExecution

    triggered_by = StandardExecution.objects.filter(
        pk__in=event.execution_ids, triggered_by_user__isnull=False
    ).values_list("triggered_by_user_id", flat=True)
    return tuple(dict.fromkeys(str(u) for u in triggered_by))


def _run_failed_notice(event: StandardRunFinished, project) -> Notice:
    from app.domain.models import StandardExecution

    rows = list(
        StandardExecution.objects.filter(
            pk__in=event.execution_ids, project=project
        ).order_by("created_at")
    )
    errored = [r for r in rows if r.status == StandardExecution.Status.ERROR]
    first = errored[0] if errored else None
    if event.error:
        body = event.error
    elif first is not None:
        # ``run_standards`` stores the error text under details["error"]; the
        # sandbox only sets the flag (``True``) and puts the traceback in
        # ``message``.
        stored = first.details.get("error")
        body = stored if isinstance(stored, str) and stored else first.message
    else:
        body = ""
    url = (
        reverse("standard_execution_detail", args=[first.pk])
        if first is not None
        else reverse("project_detail", args=[project.pk])
    )
    context = {
        "project_id": str(event.project_id),
        "project_name": project.name,
        "execution_ids": [str(e) for e in event.execution_ids],
    }
    if trigger := _trigger(rows[0] if rows else None):
        context["trigger"] = trigger
    return Notice(
        kind="run.failed",
        tenant_id=event.tenant_id,
        severity=Severity.CRITICAL,
        title="GitGrit could not evaluate",
        body=_first_line(body),
        url=url,
        context=context,
        dedupe_key=f"run_failed:{event.project_id}",
        mentioned_user_ids=_mentioned(event),
    )


def _standards_failing_notice(event: StandardRunFinished, project) -> Notice | None:
    """One notice per run. The count and the names are this run's failures
    (a single standard run by hand that fails reads "1 standard failed");
    only the score comes from the project's current picture. None when this
    run has no failed rows (a later run already passed, or the standard was
    detached): a "0 standards failed" item would be noise."""
    from app.application.project_status_service import ProjectStatusService
    from app.domain.models import StandardExecution

    failed_rows = list(
        StandardExecution.objects.filter(
            pk__in=event.execution_ids,
            project=project,
            status=StandardExecution.Status.FAILED,
        ).order_by("score")
    )
    n = len(failed_rows)
    if n == 0:
        return None
    status = ProjectStatusService().get_project_status(
        project.tenant, str(project.pk)
    )
    score = status["overall_score"]
    names = [r.standard_name for r in failed_rows[:3]]
    listing = ", ".join(names)
    if n > 3:
        listing += f" and {n - 3} more"
    # The score rides in context so the inbox can show it next to the title,
    # colored by value, instead of as text inside the body.
    context = {
        "project_id": str(event.project_id),
        "project_name": project.name,
        "execution_ids": [str(e) for e in event.execution_ids],
        "failed_standard_ids": [str(r.standard_id) for r in failed_rows],
    }
    if score is not None:
        context["score"] = round(score)
    if trigger := _trigger(failed_rows[0]):
        context["trigger"] = trigger
    return Notice(
        kind="standards.failing",
        tenant_id=event.tenant_id,
        severity=Severity.WARNING,
        title=f"{n} standard{'s' if n != 1 else ''} failed",
        body=listing,
        url=reverse("project_detail", args=[project.pk]) + "#compliance",
        context=context,
        dedupe_key=f"standards:{project.pk}",
        mentioned_user_ids=_mentioned(event),
    )


def on_standard_run_finished(event: StandardRunFinished) -> None:
    """Turn a finished run into a notice: critical when it could not be
    evaluated, a warning when standards failed."""
    outcome = _outcome(event)
    if outcome is None:
        return

    from app.domain.models import Project

    project = Project.objects.filter(
        pk=event.project_id, tenant_id=event.tenant_id
    ).first()
    if project is None:
        return
    build = (
        _run_failed_notice if outcome == "run.failed" else _standards_failing_notice
    )
    notice = build(event, project)
    if notice is not None:
        notify(notice)


def on_dependency_inference_failed(event: DependencyInferenceFailed) -> None:
    """Warn when a map that used to work fails to rebuild. A workspace that
    never had a map fails on every push, so it is not told. The graph is
    built by the LLM provider, so the notice points at that setting."""
    if not event.had_worked_before:
        return

    from app.domain.models import Project

    project = Project.objects.filter(
        pk=event.project_id, tenant_id=event.tenant_id
    ).first()
    if project is None:
        return
    notify(
        Notice(
            kind="graph.failed",
            tenant_id=event.tenant_id,
            severity=Severity.WARNING,
            title="Dependency graph failed",
            body=_first_line(event.error),
            url=reverse("tenant_settings") + "#section-llm",
            context={
                "project_id": str(event.project_id),
                "project_name": project.name,
            },
            dedupe_key=f"graph:{project.pk}",
        )
    )


def register() -> None:
    subscribe(StandardRunFinished, on_standard_run_finished)
    subscribe(DependencyInferenceFailed, on_dependency_inference_failed)
