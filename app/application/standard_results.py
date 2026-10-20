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
from app.domain.levels import DEFAULT_LEVEL, rule_for
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


@dataclass(frozen=True)
class CriticalSummary:
    """How many of a set of results are critical, and how many of those
    failed or errored in their own run (the rows the F gate reads)."""

    total: int
    failed: int


def critical_summary(results, levels_by_standard=None) -> CriticalSummary:
    """Count critical results (a level shown as critical) in ``results``
    and how many of them failed or errored in their own run. Each row is
    read by its own snapshot ``level``, or, with ``levels_by_standard``
    (standard id -> level), by its attachment's current level, as the
    project grade reads it. Running, skipped and platform-error rows do not
    count. Pure: reads only what it is given."""
    total = failed = 0
    for r in results:
        level = (
            levels_by_standard.get(r.standard_id, DEFAULT_LEVEL.value)
            if levels_by_standard is not None
            else r.level
        )
        if not rule_for(level).shown_as_critical or r.status not in FINISHED or (
            r.status == Status.ERROR and r.error_origin == StandardExecution.ErrorOrigin.PLATFORM
        ):
            continue
        total += 1
        if r.status != Status.PASSED:
            failed += 1
    return CriticalSummary(total=total, failed=failed)


def project_score(results) -> int | None:
    """The average score of a set of current results, rounded; None when
    there are none."""
    scores = [r.score for r in results if r.score is not None]
    return round(sum(scores) / len(scores)) if scores else None


@dataclass(frozen=True)
class AttentionItem:
    """One current result that did not pass."""

    tone: str  # FAILING when the standard's level is shown as critical, else ATTENTION
    standard_level: str  # the attachment's level (app.domain.levels)
    project_id: object
    project_name: str
    standard_id: object
    standard_name: str
    execution_id: object
    status: str  # display label, e.g. "Failed" or "Could not verify"
    when: datetime

    @property
    def shown_as_critical(self) -> bool:
        """Is the standard's level shown as critical?"""
        return rule_for(self.standard_level).shown_as_critical

    @property
    def level_label(self) -> str:
        return rule_for(self.standard_level).label


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
    level_of = {
        (project_id, standard_id): level
        for project_id, standard_id, level in ProjectStandard.objects.filter(
            project__in=projects
        ).values_list("project_id", "standard_id", "level")
    }
    items = []
    for ex in current_results(projects, exclude_platform_errors=True):
        if not ex.standard.enabled or ex.standard.draft or ex.status == Status.PASSED:
            continue
        standard_level = level_of.get((ex.project_id, ex.standard_id), DEFAULT_LEVEL.value)
        unverified = ex.status == Status.ERROR
        items.append(
            AttentionItem(
                tone=FAILING if rule_for(standard_level).shown_as_critical else ATTENTION,
                standard_level=standard_level,
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
        return (item.shown_as_critical, item.status != "Could not verify", item.when)

    items.sort(key=rank, reverse=True)
    return items


# --- Order on the Results tab -------------------------------------------------------

RESULT_GROUPS = (
    ("failed", "Failed standards"),
    ("passed", "Passed standards"),
    ("other", "Other"),
)


def group_results(results) -> list[tuple[str, str, list]]:
    """A commit's results for the Results tab, as ``(key, heading, results)``
    groups in display order, empty groups left out. Failed first (critical
    ones on top, then failed before errored, then by name), errored results
    count against the project so they sit with the failed; then passed; then
    "Other" (running, anything else). Order only, nothing is graded here."""

    def key_of(ex) -> str:
        if ex.status in (Status.FAILED, Status.ERROR):
            return "failed"
        return "passed" if ex.status == Status.PASSED else "other"

    def sort_key(ex):
        return (
            not rule_for(ex.level).shown_as_critical,
            ex.status != Status.FAILED,
            (ex.standard_name or "").lower(),
        )

    buckets = {key: [] for key, _ in RESULT_GROUPS}
    for ex in results:
        buckets[key_of(ex)].append(ex)
    return [
        (key, heading, sorted(buckets[key], key=sort_key))
        for key, heading in RESULT_GROUPS
        if buckets[key]
    ]
