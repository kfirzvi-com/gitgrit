"""Scoring commits and reading project scores: the database side of
``app.domain.scoring``, where every rule lives. This module loads the facts
those rules need (checks, results, scores), hands them over, and saves what
they decide.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain import scoring
from app.domain.importance import Importance
from app.domain.models import CommitCheck, CommitScore, StandardExecution
from app.domain.standard_criteria import applies

logger = logging.getLogger(__name__)

Status = StandardExecution.Status

# How many of a branch's newest checks are read to find its newest commit.
RECENT_CHECKS = 50


# --- Facts --------------------------------------------------------------------------


def _result(execution) -> scoring.Result:
    return scoring.Result(
        standard_id=str(execution.standard_id),
        name=execution.standard_name,
        status=execution.status,
        score=execution.score,
        importance=Importance(execution.importance),
        execution_id=str(execution.pk),
    )


def _commit_results(project_id, branch: str, sha: str) -> list[scoring.Result]:
    """Every result on a commit of a branch, newest first."""
    executions = StandardExecution.objects.filter(
        project_id=project_id, commit_check__branch=branch, commit_check__commit_sha=sha
    ).order_by("-created_at")
    return [_result(e) for e in executions]


def _check(check: CommitCheck) -> scoring.Check:
    return scoring.Check(
        commit_sha=check.commit_sha,
        expected_ids=tuple(check.expected_standard_ids),
        running=check.executions.filter(status=Status.RUNNING).exists(),
    )


# --- Writing ------------------------------------------------------------------------


def expected_standards(project, branch: str) -> list[str]:
    """The standards a commit on ``branch`` is expected to finish
    (``scoring.expected``), from the project's attached standards."""
    return scoring.expected(
        scoring.Candidate(
            standard_id=str(s.pk),
            enabled=s.enabled,
            draft=s.draft,
            applies=applies(
                s.criteria, project_languages=project.languages, ref=branch, skip_event_check=True
            ),
        )
        for s in project.standards.all()
    )


def score_check(check: CommitCheck) -> CommitScore | None:
    """Save the score ``scoring.score_check`` gives ``check``'s commit, if
    it gives one."""
    outcome = scoring.score_check(
        _check(check), _commit_results(check.project_id, check.branch, check.commit_sha)
    )
    if outcome is None:
        return None
    commit_score = CommitScore.objects.create(
        project_id=check.project_id,
        commit_check=check,
        branch=check.branch,
        commit_sha=check.commit_sha,
        committed_at=check.committed_at,
        ordered_at=scoring.ordered_at(check.committed_at, check.created_at),
        value=outcome.score.value,
        failed=outcome.score.failed,
        reason=outcome.score.reason,
    )
    commit_score.executions.set([r.execution_id for r in outcome.results])
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
    """Scores ordered the way ``scoring.ordered_at`` says commits are."""
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
    """Each commit's score (sha -> CommitScore, ``scoring.latest_per_commit``),
    on ``branch`` when given."""
    scores = CommitScore.objects.filter(project=project, commit_sha__in=list(shas))
    if branch is not None:
        scores = scores.filter(branch=branch)
    return scoring.latest_per_commit(scores.order_by("-created_at"))


def commit_branch(project, sha: str, score: CommitScore | None) -> str:
    """The branch ``sha`` is read on (``scoring.commit_branch``)."""
    checked = (
        CommitCheck.objects.filter(project=project, commit_sha=sha)
        .order_by("-created_at")
        .values_list("branch", flat=True)
    )
    return scoring.commit_branch(score.branch if score else None, checked, project.default_branch)


CommitState = scoring.CommitState
COMPLETE, IN_PROGRESS, INCOMPLETE = scoring.COMPLETE, scoring.IN_PROGRESS, scoring.INCOMPLETE


def commit_state(project, sha: str, branch: str) -> CommitState | None:
    """The state of ``sha`` on ``branch`` (``scoring.commit_state``); None
    when it was never checked there."""
    newest = (
        CommitCheck.objects.filter(project=project, commit_sha=sha, branch=branch)
        .order_by("-created_at")
        .first()
    )
    if newest is None:
        return None
    return scoring.commit_state(
        _check(newest),
        _commit_results(project.pk, branch, sha),
        running=StandardExecution.objects.filter(
            project=project, commit_check__commit_sha=sha, commit_check__branch=branch, status=Status.RUNNING
        ).exists(),
        scored=newest.scores.exists(),
    )


@dataclass(frozen=True)
class NewerCommit:
    """A commit newer than the scored one on the branch, not scored (yet)."""

    sha: str
    state: CommitState


def newer_commit(project, branch: str, score: CommitScore | None) -> NewerCommit | None:
    """The branch's newest checked commit (``scoring.newest_commit``) when it
    is not the scored one and has no score of its own: still checking, or
    incomplete."""
    recent = CommitCheck.objects.filter(project=project, branch=branch).exclude(commit_sha="")
    newest = scoring.newest_commit(recent.order_by("-created_at")[:RECENT_CHECKS])
    if newest is None or (score and newest.commit_sha == score.commit_sha):
        return None
    if CommitScore.objects.filter(project=project, branch=branch, commit_sha=newest.commit_sha).exists():
        return None
    state = commit_state(project, newest.commit_sha, branch)
    return NewerCommit(newest.commit_sha, state) if state else None
