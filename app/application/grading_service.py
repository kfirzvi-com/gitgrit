"""The one read behind a project's grade.

Gathers the ``Result`` of every attachment that counts: standard attached,
enabled and not draft; its latest finished execution on the standard's home
branch (``standard_results.home_branch``: the project's default branch, or
the branch the Branch/Tag Filter names literally) that was not GitGrit's own
failure; the newest commit wins. The rows come from
``standard_results.current_results``, the one definition of a project's
current results, so the grade never disagrees with the Results tab; then
``app.domain.grading`` decides the letter.

A ``Result``'s ``critical`` is the attachment's *current* mark, not the
execution's snapshot: flipping an attachment to critical while its latest
result fails shows F on the next page load, and flipping it back lifts the
gate, without a new run. The snapshot on ``StandardExecution.critical`` is
for history, which must read a run as it was marked (a standard detached
after the run still explains its old verdict). The neglect clock
``first_failed_at`` is read the same way, off the attachment.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.application.standard_results import current_results
from app.domain import grading
from app.domain.refs import home_branch
from app.domain.models import Project, ProjectStandard, Standard, StandardExecution


@dataclass(frozen=True)
class ProjectGrading:
    grade: grading.Grade
    # The counting execution per attachment, in the standards' order: the
    # rows the page shows under the letter.
    executions: list[StandardExecution]
    # Attached, enabled, non-draft standards with no counting result yet.
    # Each carries ``home_branch``, the branch it is waiting for a run on.
    not_evaluated: list[Standard]
    # Ids of the standards whose attachment is marked critical.
    critical_standard_ids: frozenset = frozenset()


def _active_attachments_by_project(projects) -> dict:
    """``{project_id: [ProjectStandard]}`` for every attachment of
    ``projects`` whose standard is enabled and not draft, in the standards'
    order. One query."""
    rows = (
        ProjectStandard.objects.filter(
            project__in=projects, standard__enabled=True, standard__draft=False
        )
        .select_related("standard")
        .order_by("project_id", "standard__ordinal", "standard__name")
    )
    by_project = defaultdict(list)
    for row in rows:
        by_project[row.project_id].append(row)
    return by_project


def _counting_results(projects, exclude_execution_ids=()) -> dict:
    """``{project_id: {standard_id: execution}}``: the latest counting
    execution per attached pair, on the pair's home branch, newest commit
    first, GitGrit's own failures skipped (the previous result stays).
    ``exclude_execution_ids`` leaves runs out: the picture before them."""
    latest = defaultdict(dict)
    for row in current_results(
        projects, exclude_execution_ids=exclude_execution_ids, exclude_platform_errors=True
    ):
        latest[row.project_id][row.standard_id] = row
    return latest


def result_for(
    execution: StandardExecution,
    critical: bool = False,
    first_failed_at=None,
) -> grading.Result:
    """``critical`` and ``first_failed_at`` are the attachment's current mark
    and neglect clock (see the module doc)."""
    return grading.Result(
        status=execution.status,
        critical=critical,
        error_origin=execution.error_origin,
        name=execution.standard_name,
        first_failed_at=first_failed_at,
    )


def _results(executions, attachments: dict):
    for ex in executions:
        attachment = attachments.get(ex.standard_id)
        yield result_for(
            ex,
            critical=bool(attachment and attachment.critical),
            first_failed_at=attachment.first_failed_at if attachment else None,
        )


def _grading(project, attachments, found: dict) -> ProjectGrading:
    executions = [found[a.standard_id] for a in attachments if a.standard_id in found]
    not_evaluated = []
    for attachment in attachments:
        if attachment.standard_id in found:
            continue
        standard = attachment.standard
        standard.home_branch = home_branch(project.default_branch, standard.criteria or {})
        not_evaluated.append(standard)
    grade = grading.letter_for(
        _results(executions, {a.standard_id: a for a in attachments})
    )
    return ProjectGrading(
        grade=grade,
        executions=executions,
        not_evaluated=not_evaluated,
        critical_standard_ids=frozenset(a.standard_id for a in attachments if a.critical),
    )


def grade_for_project(project: Project, exclude_execution_ids=()) -> ProjectGrading:
    """The project's grade, the executions it was read from, and the
    attachments that have nothing to read yet. ``exclude_execution_ids``
    reads the grade as it was before those runs (a notification policy
    compares the two)."""
    attachments = _active_attachments_by_project([project]).get(project.pk, [])
    found = _counting_results([project], exclude_execution_ids).get(project.pk, {})
    return _grading(project, attachments, found)


def grades_for_tenant(tenant) -> dict:
    """``{project_id: ProjectGrading}`` for every project in the workspace,
    by the same rules as ``grade_for_project``, in a fixed number of queries
    instead of a few per project. Projects with no active attachment get no
    grade."""
    projects = list(Project.objects.filter(tenant=tenant))
    attachments = _active_attachments_by_project(projects)
    latest = _counting_results(projects)
    return {
        project.pk: _grading(
            project, attachments.get(project.pk, []), latest.get(project.pk, {})
        )
        for project in projects
    }


def letter_for_projects(project_ids, grades: dict) -> str:
    """The worst letter among the given projects' grades (a stack or the
    whole workspace); projects with no grade are ignored."""
    return grading.worst_letter(
        grades[pid].grade.letter for pid in project_ids if pid in grades
    )
