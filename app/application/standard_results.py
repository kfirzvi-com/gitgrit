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
from django.db.models.functions import Coalesce

from app.domain.health import ATTENTION, FAILING
from app.domain.models import Project, ProjectStandard, StandardExecution
from app.domain.refs import home_branch

Status = StandardExecution.Status
FINISHED = (Status.PASSED, Status.FAILED, Status.ERROR)


def current_results(
    projects,
    statuses=FINISHED,
    exclude_execution_ids=(),
    branch=None,
    exclude_platform_errors=False,
):
    """The latest result per attached (project, standard) pair on that pair's
    home branch, as ``StandardExecution`` rows with project and standard
    loaded. ``statuses`` picks which results count (finished ones by
    default); ``exclude_execution_ids`` leaves runs out, which gives the
    picture as it was before them. ``branch`` reads every pair on that branch
    instead of its home branch: a branch's own status, not the project's
    health. ``exclude_platform_errors`` skips ERROR rows that were GitGrit's
    own failure (a stale sweep, a job or sandbox error), so the pair's
    previous result stays current: the grade reads this way."""
    pairs = ProjectStandard.objects.filter(project__in=projects).select_related(
        "project", "standard"
    )
    on_home_branch = Q()
    for pair in pairs:
        home = (
            branch
            if branch is not None
            else home_branch(pair.project.default_branch, pair.standard.criteria or {})
        )
        refs = Q(ref=home) | Q(ref=f"refs/heads/{home}")
        if home == pair.project.default_branch:
            refs |= Q(ref="")
        on_home_branch |= Q(project_id=pair.project_id, standard_id=pair.standard_id) & refs
    if not on_home_branch:
        return []
    # The newest *commit* wins, not the newest run: checking an old commit
    # again must not change the picture. Runs of the same commit (and runs
    # with no known commit date) go by when they ran.
    committed = Coalesce("commit_check__committed_at", "created_at")
    rows = StandardExecution.objects.filter(on_home_branch, status__in=statuses).exclude(
        pk__in=list(exclude_execution_ids)
    )
    if exclude_platform_errors:
        rows = rows.exclude(
            status=Status.ERROR, error_origin=StandardExecution.ErrorOrigin.PLATFORM
        )
    return list(
        rows
        .select_related("project", "standard", "commit_check")
        .order_by("project_id", "standard_id", committed.desc(), "-created_at")
        .distinct("project_id", "standard_id")
    )


def breakdown(results) -> dict:
    """How many of a set of results passed, failed and errored."""
    statuses = [r.status for r in results]
    return {
        "passed": statuses.count(Status.PASSED),
        "failed": statuses.count(Status.FAILED),
        "errored": statuses.count(Status.ERROR),
    }


def project_score(results) -> int | None:
    """The average score of a set of current results, rounded; None when
    there are none."""
    scores = [r.score for r in results if r.score is not None]
    return round(sum(scores) / len(scores)) if scores else None


@dataclass(frozen=True)
class AttentionItem:
    """One current result that did not pass."""

    level: str  # FAILING when the standard is critical, else ATTENTION
    critical: bool
    project_id: object
    project_name: str
    standard_id: object
    standard_name: str
    execution_id: object
    status: str  # display label, e.g. "Failed" or "Could not verify"
    when: datetime


def attention_items(tenant) -> list[AttentionItem]:
    """Current results that need attention: the latest counting result per
    (project, standard) that did not pass, ranked critical first (they make
    the project an F), then failed, then errored, newest first within each.

    Only results that move a grade are listed (``app.domain.grading``): the
    standard is attached, enabled and not a draft; the run read the
    standard's home branch; GitGrit's own failures are skipped, so the
    pair's previous result stands. Returns the full ranked list; screens
    decide how many to show.
    """
    projects = Project.objects.filter(tenant=tenant)
    critical_pairs = set(
        ProjectStandard.objects.filter(project__in=projects, critical=True).values_list(
            "project_id", "standard_id"
        )
    )
    items = []
    for ex in current_results(projects, exclude_platform_errors=True):
        if not ex.standard.enabled or ex.standard.draft or ex.status == Status.PASSED:
            continue
        critical = (ex.project_id, ex.standard_id) in critical_pairs
        unverified = ex.status == Status.ERROR
        items.append(
            AttentionItem(
                level=FAILING if critical else ATTENTION,
                critical=critical,
                project_id=ex.project_id,
                project_name=ex.project.name,
                standard_id=ex.standard_id,
                standard_name=ex.standard_name,
                execution_id=ex.id,
                status="Could not verify" if unverified else ex.get_status_display(),
                when=ex.created_at,
            )
        )

    def rank(item):
        return (item.critical, item.status != "Could not verify", item.when)

    items.sort(key=rank, reverse=True)
    return items
