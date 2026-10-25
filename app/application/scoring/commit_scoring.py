"""Scoring commits and reading branch and project scores: the database side
of ``app.domain.scoring``, where every rule lives. This module only loads a
check's facts into a ``scoring.CheckRun`` (``_runs_of``), asks it, and saves
what it decides.

A commit reads its newest check, alone; a branch reads its newest commit
(``scoring.BranchCommitTimeline.newest_checked_commit``), whatever its
outcome; a project reads its default branch.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from django.db.models import Q
from django.db.models.functions import Coalesce

from app.application.scoring.check_run_record import CheckRunRecord
from app.domain import scoring
from app.domain.importance import Importance
from app.domain.models import CommitCheck, CommitScore, Standard, StandardExecution
from app.domain.standard_criteria import applies

logger = logging.getLogger(__name__)

# How many of a branch's newest checks are read to find its newest commit.
RECENT_CHECKS = 50

# How a standard the check expected but that no longer exists is named.
REMOVED_STANDARD = "a removed standard"


# --- Facts --------------------------------------------------------------------------


def _run_result(execution) -> scoring.StandardRunResult:
    return scoring.StandardRunResult(
        # A run of a standard deleted since has no standard left.
        standard_id=str(execution.standard_id) if execution.standard_id else "",
        standard_name=execution.standard_name,
        status=scoring.StandardRunStatus(execution.status),
        standard_score=execution.score,
        importance=Importance(execution.importance),
        execution_id=str(execution.pk),
    )


def _standard_names(expected_ids) -> dict[str, str]:
    """Each expected standard's name (id -> name), archived ones included, to
    name the ones that never ran."""
    ids = [str(i) for i in expected_ids]
    names = {str(pk): name for pk, name in Standard.all_objects.filter(pk__in=ids).values_list("pk", "name")}
    return {i: names.get(i, REMOVED_STANDARD) for i in ids}


def _saved_value(score: CommitScore | None) -> scoring.CommitScoreValue | None:
    if score is None:
        return None
    return scoring.CommitScoreValue(score.value, failed_by_required_standard=score.failed, reason=score.reason)


def _runs_of(checks) -> dict:
    """Each check as a ``CheckRunRecord`` (check id -> record): its domain
    ``scoring.CheckRun`` built from its facts, beside its rows. A few queries
    for them all."""
    checks = list(checks)
    if not checks:
        return {}
    executions = defaultdict(list)
    for ex in (
        StandardExecution.objects.filter(commit_check__in=checks)
        .select_related("standard", "standard_version", "commit_check")
        .order_by("-created_at")
    ):
        executions[ex.commit_check_id].append(ex)
    scores = {
        s.commit_check_id: s
        for s in CommitScore.objects.filter(commit_check__in=checks)
        .order_by("commit_check_id", "-created_at")
        .distinct("commit_check_id")
    }
    names = _standard_names({i for c in checks for i in c.expected_standard_ids})
    records = {}
    for check in checks:
        own = executions[check.pk]
        run = scoring.CheckRun(
            commit_sha=check.commit_sha,
            expected=scoring.ExpectedStandards(tuple(check.expected_standard_ids)),
            results=tuple(_run_result(e) for e in own),
            standard_names=names,
            saved=_saved_value(scores.get(check.pk)),
        )
        score = None if run.running else scores.get(check.pk)
        records[check.pk] = CheckRunRecord(check=check, run=run, executions=tuple(own), score=score)
    return records


# --- Writing ------------------------------------------------------------------------


def expected_standards(project, branch: str) -> list[str]:
    """The standards a commit on ``branch`` is expected to finish
    (``scoring.ExpectedStandards.from_attached``), from the project's
    attached standards."""
    return list(
        scoring.ExpectedStandards.from_attached(
            scoring.AttachedStandard(
                standard_id=str(s.pk),
                enabled=s.enabled,
                draft=s.draft,
                matches_criteria=applies(
                    s.criteria, project_languages=project.languages, ref=branch, skip_event_check=True
                ),
            )
            for s in project.standards.all()
        ).standard_ids
    )


def score_check(check: CommitCheck) -> CommitScore | None:
    """Save the score ``check`` gives its commit (``scoring.CheckRun.decide``)
    once none of its runs is going: a verdict, or no score and why."""
    new_score = _runs_of([check])[check.pk].run.decide()
    if new_score is None:
        return None
    commit_score = CommitScore.objects.create(
        project_id=check.project_id,
        commit_check=check,
        branch=check.branch,
        commit_sha=check.commit_sha,
        committed_at=check.committed_at,
        ordered_at=scoring.BranchCommitTimeline.commit_ordered_at(check.committed_at, check.created_at),
        value=new_score.score.value,
        failed=new_score.score.failed_by_required_standard,
        reason=new_score.score.reason,
    )
    commit_score.executions.set([r.execution_id for r in new_score.run_results])
    return commit_score


def score_checks(check_ids) -> list[CommitScore]:
    """Score every check among ``check_ids`` that gives its commit a score."""
    scores = []
    for check in CommitCheck.objects.filter(pk__in=list(check_ids)).order_by("created_at"):
        scored = score_check(check)
        if scored:
            scores.append(scored)
    return scores


# --- Reading: checks ------------------------------------------------------------------


def commit_history(project, shas, branch: str | None = None) -> dict:
    """Each commit's checks (sha -> [CheckRunRecord], oldest first; on ``branch``
    when given): every run of the standards on it. The newest is the
    commit's outcome."""
    checks = CommitCheck.objects.filter(project=project, commit_sha__in=list(shas)).order_by("created_at")
    if branch is not None:
        checks = checks.filter(branch=branch)
    checks = list(checks)
    runs = _runs_of(checks)
    history = defaultdict(list)
    for check in checks:
        history[check.commit_sha].append(runs[check.pk])
    return dict(history)


def check_run(project, check_id) -> CheckRunRecord | None:
    """One check of the project as a ``CheckRunRecord``; None when it is not the
    project's."""
    check = CommitCheck.objects.filter(project=project, pk=check_id).first()
    return _runs_of([check])[check.pk] if check else None


# --- Reading: branches and projects ---------------------------------------------------


def _recent_checks(project, branch: str):
    return (
        CommitCheck.objects.filter(project=project, branch=branch)
        .exclude(commit_sha="")
        .order_by("-created_at")[:RECENT_CHECKS]
    )


def branch_head(project, branch: str) -> CheckRunRecord | None:
    """What ``branch`` reads: its newest commit's newest check
    (``scoring.BranchCommitTimeline.newest_checked_commit``), whatever its
    outcome: checking, no score, failed or scored. None when nothing on it
    was checked."""
    check = scoring.BranchCommitTimeline.newest_checked_commit(_recent_checks(project, branch))
    return _runs_of([check])[check.pk] if check else None


def project_heads(projects) -> dict:
    """Each project's ``branch_head`` on its default branch (project id ->
    CheckRunRecord), read for them all at once. The query orders checks the way
    ``scoring.BranchCommitTimeline.newest_checked_commit`` does."""
    projects = list(projects)
    if not projects:
        return {}
    on_default_branch = Q()
    for p in projects:
        on_default_branch |= Q(project_id=p.pk, branch=p.default_branch)
    heads = list(
        CommitCheck.objects.filter(on_default_branch)
        .exclude(commit_sha="")
        .annotate(commit_ordered_at=Coalesce("committed_at", "created_at"))
        .order_by("project_id", "-commit_ordered_at", "-created_at")
        .distinct("project_id")
    )
    runs = _runs_of(heads)
    return {check.project_id: runs[check.pk] for check in heads}


def _newest_first(queryset):
    """Scores ordered the way ``scoring.BranchCommitTimeline`` orders commits."""
    return queryset.order_by("-ordered_at", "-created_at")


def branch_score(project, branch: str, excluding=()) -> CommitScore | None:
    """The score ``branch`` reads (``branch_head``): its newest commit's,
    failed, scored or no score; None while that commit is being checked or
    when nothing was. ``excluding`` (execution ids) gives the branch's score
    as it was before a run: its newest score not decided from them."""
    if excluding:
        scores = CommitScore.objects.filter(project=project, branch=branch).exclude(executions__in=list(excluding))
        return _newest_first(scores).first()
    head = branch_head(project, branch)
    return head.score if head else None


def project_score(project, excluding=()) -> CommitScore | None:
    """The project's score: its default branch's (see ``branch_score``)."""
    return branch_score(project, project.default_branch, excluding=excluding)


def project_scores(projects) -> dict:
    """Each project's score (project id -> CommitScore; see
    ``project_heads``), with the results it was decided from prefetched.
    Projects being checked, or never checked, are left out."""
    heads = project_heads(projects)
    by_id = {
        s.pk: s
        for s in CommitScore.objects.filter(pk__in=[h.score.pk for h in heads.values() if h.score]).prefetch_related(
            "executions"
        )
    }
    return {pid: by_id[head.score.pk] for pid, head in heads.items() if head.score}


def commit_scores(project, shas, branch: str | None = None) -> dict[str, CommitScore]:
    """Each commit's score (sha -> CommitScore,
    ``scoring.BranchCommitTimeline.last_score_per_commit``), on ``branch`` when
    given."""
    scores = CommitScore.objects.filter(project=project, commit_sha__in=list(shas))
    if branch is not None:
        scores = scores.filter(branch=branch)
    return scoring.BranchCommitTimeline.last_score_per_commit(scores.order_by("-created_at"))


def commit_branch(project, sha: str, score: CommitScore | None) -> str:
    """The branch ``sha`` is read on
    (``scoring.BranchCommitTimeline.branch_a_commit_is_read_on``)."""
    checked = (
        CommitCheck.objects.filter(project=project, commit_sha=sha)
        .order_by("-created_at")
        .values_list("branch", flat=True)
    )
    return scoring.BranchCommitTimeline.branch_a_commit_is_read_on(
        score.branch if score else None, checked, project.default_branch
    )


def commit_standing(project, sha: str, branch: str) -> scoring.CommitStanding | None:
    """Where ``sha`` stands on ``branch``: its newest check's outcome. None
    when it was never checked there."""
    newest = (
        CommitCheck.objects.filter(project=project, commit_sha=sha, branch=branch).order_by("-created_at").first()
    )
    return _runs_of([newest])[newest.pk].standing if newest else None
