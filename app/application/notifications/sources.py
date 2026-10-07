"""Sources: translators from domain events to notices.

A source turns a fact into a ``Notice`` and hands it to ``notify()``. It never
decides the audience; the rule table in ``router.py`` does. A finished run
yields ``run.failed`` (could not evaluate) or ``standards.failing``; a
dependency graph that gave up building yields ``graph.failed``. Every kind
goes to the whole team (see ``router.py``); the run's trigger is added on top.
"""

from __future__ import annotations

from django.urls import reverse

from app.application.event_bus import subscribe
from app.application.notifications import notify
from app.domain.events import DependencyInferenceFailed, StandardRunFinished
from app.domain.notifications import Notice, Severity

_BODY_MAX = 200


_TRACEBACK = "Traceback (most recent call last):"


def _first_line(text: str) -> str:
    """One line of body text. A traceback's useful line is its last one
    (the exception); any other text is summarized by its first line."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[-1] if any(_TRACEBACK in line for line in lines) else lines[0]
    return line[:_BODY_MAX]


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
            pk__in=event.execution_ids,
            project=project,
            status=StandardExecution.Status.ERROR,
        ).order_by("created_at")
    )
    first = rows[0] if rows else None
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
    return Notice(
        kind="run.failed",
        tenant_id=event.tenant_id,
        severity=Severity.CRITICAL,
        title=f"{project.name} GitGrit could not evaluate",
        body=_first_line(body),
        url=url,
        context={
            "project_id": str(event.project_id),
            "execution_ids": [str(e) for e in event.execution_ids],
        },
        dedupe_key=f"run_failed:{event.project_id}",
        mentioned_user_ids=_mentioned(event),
    )


def _standards_failing_notice(event: StandardRunFinished, project) -> Notice | None:
    """One notice per run. Count and score come from the project's current
    picture; the names come from this run's failures. None when the current
    picture shows nothing failing (a later run already passed, or the
    standard was detached): a "0 standards failing" item would be noise."""
    from app.application.project_status_service import ProjectStatusService
    from app.domain.models import StandardExecution

    status = ProjectStatusService().get_project_status(
        project.tenant, str(project.pk)
    )
    n = status["failed"]
    if n == 0:
        return None
    score = status["overall_score"]
    failed_rows = list(
        StandardExecution.objects.filter(
            pk__in=event.execution_ids,
            project=project,
            status=StandardExecution.Status.FAILED,
        ).order_by("score")
    )
    names = [r.standard_name for r in failed_rows[:3]]
    listing = ", ".join(names)
    if len(failed_rows) > 3:
        listing += f" and {len(failed_rows) - 3} more"
    # The score rides in context so the inbox can show it next to the title,
    # colored by value, instead of as text inside the body.
    context = {
        "project_id": str(event.project_id),
        "execution_ids": [str(e) for e in event.execution_ids],
        "failed_standard_ids": [str(r.standard_id) for r in failed_rows],
    }
    if score is not None:
        context["score"] = round(score)
    return Notice(
        kind="standards.failing",
        tenant_id=event.tenant_id,
        severity=Severity.WARNING,
        title=f"{project.name} {n} standard{'s' if n != 1 else ''} failed",
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
    never had a map fails on every push, so it is not told."""
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
            title=f"{project.name} dependency graph failed",
            body=_first_line(event.error),
            url=reverse("project_detail", args=[project.pk]) + "#components",
            context={"project_id": str(event.project_id)},
            dedupe_key=f"graph:{project.pk}",
        )
    )


def register() -> None:
    subscribe(StandardRunFinished, on_standard_run_finished)
    subscribe(DependencyInferenceFailed, on_dependency_inference_failed)
