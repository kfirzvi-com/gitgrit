"""Reads of a project's current standard results: the one definition of
project health.

A project's health is read from each attached standard's latest finished
result **on that standard's home branch**: the project's default branch,
unless the standard's Branch/Tag Filter names one branch literally. Runs on
other branches (a feature-branch push, a pull request) show in the project's
activity but never move its health: a half-finished branch must not make the
project look critical, and a fix that only exists on a branch must not make
it look healthy before it merges.

Every screen that scores projects or lists problems reads from here (the
dashboard, the stack diagram, the project page, the badge, the project
status service, "Needs attention"), so they never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

from app.application.standard_engine import literal_ref
from app.domain.health import CRITICAL, HEALTHY, WARNING, level_from_score
from app.domain.models import Project, ProjectStandard, StandardExecution

Status = StandardExecution.Status
FINISHED = (Status.PASSED, Status.FAILED, Status.ERROR)


def home_branch(project, standard) -> str:
    """The branch a standard's results count on for ``project``."""
    criteria = standard.criteria or {}
    return literal_ref(criteria.get("ref")) or project.default_branch


def current_results(projects, statuses=FINISHED, exclude_execution_ids=()):
    """The latest result per attached (project, standard) pair on that pair's
    home branch, as ``StandardExecution`` rows with project and standard
    loaded. ``statuses`` picks which results count (finished ones by
    default); ``exclude_execution_ids`` leaves runs out, which gives the
    picture as it was before them."""
    pairs = ProjectStandard.objects.filter(project__in=projects).select_related(
        "project", "standard"
    )
    on_home_branch = Q()
    for pair in pairs:
        home = home_branch(pair.project, pair.standard)
        refs = Q(ref=home) | Q(ref=f"refs/heads/{home}")
        if home == pair.project.default_branch:
            refs |= Q(ref="")
        on_home_branch |= Q(project_id=pair.project_id, standard_id=pair.standard_id) & refs
    if not on_home_branch:
        return []
    return list(
        StandardExecution.objects.filter(on_home_branch, status__in=statuses)
        .exclude(pk__in=list(exclude_execution_ids))
        .select_related("project", "standard")
        .order_by("project_id", "standard_id", "-created_at")
        .distinct("project_id", "standard_id")
    )


def project_score(results) -> int | None:
    """The average score of a set of current results, rounded; None when
    there are none."""
    scores = [r.score for r in results if r.score is not None]
    return round(sum(scores) / len(scores)) if scores else None


@dataclass(frozen=True)
class AttentionItem:
    """One current result that needs attention."""

    level: str  # WARNING or CRITICAL
    project_id: object
    project_name: str
    standard_id: object
    standard_name: str
    execution_id: object
    score: int
    status: str  # display label, e.g. "Failed"
    when: datetime


def attention_items(tenant) -> list[AttentionItem]:
    """Current results that need attention, critical first, then newest.

    A result needs attention when its score is below healthy, or when it
    failed or errored at all (a failed run that still scored well is a
    warning). Returns the full ranked list; screens decide how many to show.
    """
    items = []
    for ex in current_results(Project.objects.filter(tenant=tenant)):
        level = level_from_score(ex.score)
        failed = ex.status in (Status.FAILED, Status.ERROR)
        if level == HEALTHY and not failed:
            continue
        if level == HEALTHY:
            level = WARNING
        items.append(
            AttentionItem(
                level=level,
                project_id=ex.project_id,
                project_name=ex.project.name,
                standard_id=ex.standard_id,
                standard_name=ex.standard_name,
                execution_id=ex.id,
                score=ex.score,
                status=ex.get_status_display(),
                when=ex.created_at,
            )
        )

    rank = {CRITICAL: 2, WARNING: 1}
    items.sort(key=lambda i: (rank.get(i.level, 0), i.when), reverse=True)
    return items
