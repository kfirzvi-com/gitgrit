"""Lookups behind the could-not-verify alert (``Kind.GRADE_UNVERIFIED``).

A finished run raises the alert for a critical attachment only on the
transition: this run left it errored inside its own code, and its previous
counting result on the standard's home branch was not errored (or there was
none). ``app.domain.grading.unverified_transition`` decides; this module
finds the rows to feed it. The inbox has no dedupe, so the transition rule
is the dedupe: a repeat error is silent, and after a pass the next error
speaks again.

"Counting" is the grade's own reading (``grading_service``, over
``standard_results.current_results``): the pair's latest finished result on
its home branch, newest commit first, GitGrit's own failures skipped. So a
run on another branch, an older commit or a platform error never
transitions, and critical is the attachment's *current* mark: a standard
detached or unmarked between the run and this lookup stays quiet.
"""

from __future__ import annotations

from functools import cached_property

from app.application import grading_service
from app.domain import grading
from app.domain.models import Project, StandardExecution


class RunPictures:
    """The two grade pictures of one finished run, each read once: ``after``
    (the project's grade now) and ``before`` (as it was without this run's
    rows). The notification policies of one event share one instance, so the
    reads are not repeated per policy."""

    def __init__(self, project: Project, run_ids) -> None:
        self.project = project
        self.run_ids = tuple(str(i) for i in run_ids)

    @cached_property
    def after(self) -> grading_service.ProjectGrading:
        return grading_service.grade_for_project(self.project)

    @cached_property
    def before(self) -> grading_service.ProjectGrading:
        return grading_service.grade_for_project(
            self.project, exclude_execution_ids=self.run_ids
        )


_last: tuple | None = None


def pictures_for(event, project: Project) -> RunPictures:
    """The ``RunPictures`` of ``event``: the same object for every policy
    handling that event (the bus hands each the one event instance), a fresh
    one for the next event."""
    global _last
    if _last is not None and _last[0] is event and _last[1].project.pk == project.pk:
        return _last[1]
    pictures = RunPictures(project, event.execution_ids)
    _last = (event, pictures)
    return pictures


def unverified_transitions(pictures: RunPictures) -> list[StandardExecution]:
    """This run's rows that just flipped a critical attachment into "could
    not verify", in the standards' order. Empty when nothing transitioned:
    no critical attachment's counting result is an own-code error of this
    run, or every one that is was already errored before this run."""
    run_ids = set(pictures.run_ids)
    after = pictures.after
    candidates = [
        ex
        for ex in after.executions
        if str(ex.pk) in run_ids
        and ex.standard_id in after.critical_standard_ids
        and ex.status == StandardExecution.Status.ERROR
    ]
    if not candidates:
        return []
    before = {row.standard_id: row for row in pictures.before.executions}
    transitioned = []
    for row in candidates:
        current = grading_service.result_for(row, critical=True)
        earlier = before.get(row.standard_id)
        previous = grading_service.result_for(earlier, critical=True) if earlier else None
        if grading.unverified_transition(previous, current):
            transitioned.append(row)
    return transitioned
