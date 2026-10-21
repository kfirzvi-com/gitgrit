"""Scoring commits and reading project scores: the database side of
``app.domain.scoring``, where every rule lives. This module loads the facts
those rules need (checks, results, scores), hands them over, and saves what
they decide.
"""
from __future__ import annotations

import logging

from app.application.scoring.newer_commit import NewerCommit
from app.domain import scoring
from app.domain.importance import Importance
from app.domain.models import CommitCheck, CommitScore, StandardExecution
from app.domain.standard_criteria import applies

logger = logging.getLogger(__name__)

Status = StandardExecution.Status

# How many of a branch's newest checks are read to find its newest commit.
RECENT_CHECKS = 50


# --- Facts --------------------------------------------------------------------------


def _run_result(execution) -> scoring.StandardRunResult:
    return scoring.StandardRunResult(
        standard_id=str(execution.standard_id),
        standard_name=execution.standard_name,
        status=scoring.StandardRunStatus(execution.status),
        standard_score=execution.score,
        importance=Importance(execution.importance),
        execution_id=str(execution.pk),
    )


def _runs_on_commit(project_id, branch: str, sha: str) -> scoring.StandardRunResultsOnCommit:
    """Every standard run on a commit of a branch, newest first."""
    executions = StandardExecution.objects.filter(
        project_id=project_id, commit_check__branch=branch, commit_check__commit_sha=sha
    ).order_by("-created_at")
    return scoring.StandardRunResultsOnCommit(_run_result(e) for e in executions)


def _scorable(check: CommitCheck) -> scoring.ScorableCommitCheck:
    return scoring.ScorableCommitCheck(
        commit_sha=check.commit_sha,
        expected_standards=scoring.ExpectedStandards(tuple(check.expected_standard_ids)),
        has_running_runs=check.executions.filter(status=Status.RUNNING).exists(),
    )


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
    """Save the score ``check`` gives its commit
    (``scoring.ScorableCommitCheck.new_commit_score``), if it gives one."""
    new_score = _scorable(check).new_commit_score(
        _runs_on_commit(check.project_id, check.branch, check.commit_sha)
    )
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
        reason=new_score.score.failure_reason,
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


# --- Reading ------------------------------------------------------------------------


def _newest_first(queryset):
    """Scores ordered the way ``scoring.BranchCommitTimeline`` orders commits."""
    return queryset.order_by("-ordered_at", "-created_at")


def branch_score(project, branch: str, excluding=()) -> CommitScore | None:
    """The score of the newest scored commit on ``branch``. ``excluding``
    (execution ids) leaves out scores computed from those results, which
    gives the branch's score as it was before a run."""
    scores = CommitScore.objects.filter(project=project, branch=branch)
    if excluding:
        scores = scores.exclude(executions__in=list(excluding))
    return _newest_first(scores).first()


def project_score(project, excluding=()) -> CommitScore | None:
    """The project's score: its default branch's (see ``branch_score``)."""
    return branch_score(project, project.default_branch, excluding=excluding)


def project_scores(projects) -> dict:
    """Each project's score (project id -> CommitScore), read in one query,
    with the scored results prefetched."""
    projects = list(projects)
    default_branch = {p.pk: p.default_branch for p in projects}
    picked = {}
    scores = _newest_first(CommitScore.objects.filter(project__in=projects)).prefetch_related("executions")
    for score in scores:
        if score.branch == default_branch[score.project_id]:
            picked.setdefault(score.project_id, score)
    return picked


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


CommitScoringState = scoring.CommitScoringState
COMPLETE = CommitScoringState.COMPLETE
IN_PROGRESS = CommitScoringState.IN_PROGRESS
INCOMPLETE = CommitScoringState.INCOMPLETE


def commit_state(project, sha: str, branch: str) -> CommitScoringState | None:
    """The scoring state of ``sha`` on ``branch``
    (``scoring.ScorableCommitCheck.commit_scoring_state`` of its newest
    check); None when it was never checked there."""
    newest = (
        CommitCheck.objects.filter(project=project, commit_sha=sha, branch=branch)
        .order_by("-created_at")
        .first()
    )
    if newest is None:
        return None
    return _scorable(newest).commit_scoring_state(
        _runs_on_commit(project.pk, branch, sha),
        any_run_going=StandardExecution.objects.filter(
            project=project, commit_check__commit_sha=sha, commit_check__branch=branch, status=Status.RUNNING
        ).exists(),
        scored_by_this_check=newest.scores.exists(),
    )


def newer_commit(project, branch: str, score: CommitScore | None) -> NewerCommit | None:
    """The branch's newest checked commit
    (``scoring.BranchCommitTimeline.newest_checked_commit``) when it
    is not the scored one and has no score of its own: still checking, or
    incomplete."""
    recent = CommitCheck.objects.filter(project=project, branch=branch).exclude(commit_sha="")
    newest = scoring.BranchCommitTimeline.newest_checked_commit(recent.order_by("-created_at")[:RECENT_CHECKS])
    if newest is None or (score and newest.commit_sha == score.commit_sha):
        return None
    if CommitScore.objects.filter(project=project, branch=branch, commit_sha=newest.commit_sha).exists():
        return None
    state = commit_state(project, newest.commit_sha, branch)
    return NewerCommit(newest.commit_sha, state) if state else None
