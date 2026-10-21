"""Scoring commits and reading project scores.

A check records the standards it expects when it is queued
(``expected_standards``). When a check finishes, ``score_check`` looks at its
commit: if every expected standard has a finished result there (the newest
one per standard, across all of the commit's checks on that branch), the
commit gets a new ``CommitScore`` from ``app.domain.scoring``; if not, the
commit keeps the score it had. The project's score is the newest commit
score on its default branch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db.models import F
from django.db.models.functions import Coalesce

from app.application.standard_engine import StandardEngine
from app.domain import scoring
from app.domain.importance import Importance
from app.domain.models import CommitCheck, CommitScore, StandardExecution

logger = logging.getLogger(__name__)

Status = StandardExecution.Status


# --- Writing ----------------------------------------------------------------------


def expected_standards(project, branch: str) -> list[str]:
    """The standards a commit on ``branch`` needs a finished result of to be
    scored: the project's attached, enabled, non-draft standards that match
    the branch and the project's languages. Standard ids."""
    return [str(s.pk) for s in StandardEngine().standards_for_branch(project, branch)]


def _as_result(execution) -> scoring.Result:
    return scoring.Result(
        standard_id=str(execution.standard_id),
        name=execution.standard_name,
        status=execution.status,
        score=execution.score,
        importance=Importance(execution.importance),
    )


def commit_results(check: CommitCheck) -> list[StandardExecution]:
    """The newest finished result of each standard ``check`` expects, across
    every check of its commit on its branch."""
    expected = {str(i) for i in check.expected_standard_ids}
    newest = {}
    executions = (
        StandardExecution.objects.filter(
            project_id=check.project_id,
            commit_check__branch=check.branch,
            commit_check__commit_sha=check.commit_sha,
            status__in=scoring.FINISHED,
        )
        .order_by("-created_at")
    )
    for execution in executions:
        key = str(execution.standard_id)
        if key in expected and key not in newest:
            newest[key] = execution
    return list(newest.values())


def score_check(check: CommitCheck) -> CommitScore | None:
    """Score ``check``'s commit if the check has finished and the commit is
    complete. Returns the new score, or None (still running, no commit, or
    incomplete: the commit keeps the score it had). A check that expects
    nothing (none of its standards applies, or it predates expectations)
    scores nothing."""
    if not check.commit_sha or not check.expected_standard_ids:
        return None
    if check.executions.filter(status=Status.RUNNING).exists():
        return None
    results = commit_results(check)
    as_results = [_as_result(e) for e in results]
    if scoring.missing(check.expected_standard_ids, as_results):
        logger.info("Commit %s of %s is incomplete; keeping its score", check.commit_sha[:7], check.project_id)
        return None
    outcome = scoring.score(as_results)
    commit_score = CommitScore.objects.create(
        project_id=check.project_id,
        commit_check=check,
        branch=check.branch,
        commit_sha=check.commit_sha,
        committed_at=check.committed_at,
        value=outcome.value,
        failed=outcome.failed,
        reason=outcome.reason,
    )
    commit_score.executions.set(results)
    return commit_score


def score_checks(check_ids) -> list[CommitScore]:
    """Score every finished, complete check among ``check_ids``."""
    scores = []
    for check in CommitCheck.objects.filter(pk__in=list(check_ids)).order_by("created_at"):
        scored = score_check(check)
        if scored:
            scores.append(scored)
    return scores


# --- Reading ----------------------------------------------------------------------


def _newest_first(queryset):
    """A branch's scores, newest commit first: checking an old commit again
    must not replace the score of a newer one."""
    return queryset.order_by(
        Coalesce("committed_at", "commit_check__created_at").desc(), F("created_at").desc()
    )


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


def commit_scores(project, shas, branch: str | None = None) -> dict[str, CommitScore]:
    """Each commit's latest score (sha -> CommitScore), on ``branch`` when
    given."""
    scores = CommitScore.objects.filter(project=project, commit_sha__in=list(shas))
    if branch is not None:
        scores = scores.filter(branch=branch)
    latest = {}
    for score in scores.order_by("-created_at"):
        latest.setdefault(score.commit_sha, score)
    return latest


@dataclass(frozen=True)
class CommitState:
    """Where a commit stands: ``complete`` (scored, nothing newer pending),
    ``in_progress`` (a check is still running) or ``incomplete`` (its last
    check finished without completing it). ``expected`` and ``finished``
    count the standards of its newest check."""

    state: str
    expected: int
    finished: int


COMPLETE, IN_PROGRESS, INCOMPLETE = "complete", "in_progress", "incomplete"


def commit_state(project, sha: str, branch: str) -> CommitState | None:
    """The state of ``sha`` on ``branch``, from its newest check; None when
    it was never checked."""
    check = (
        CommitCheck.objects.filter(project=project, commit_sha=sha, branch=branch)
        .order_by("-created_at")
        .first()
    )
    if check is None or not check.expected_standard_ids:
        return None
    expected = len(check.expected_standard_ids)
    if StandardExecution.objects.filter(
        project=project, commit_check__commit_sha=sha, commit_check__branch=branch, status=Status.RUNNING
    ).exists():
        finished = expected - len(scoring.missing(check.expected_standard_ids, [_as_result(e) for e in commit_results(check)]))
        return CommitState(IN_PROGRESS, expected, finished)
    if check.scores.exists():
        return CommitState(COMPLETE, expected, expected)
    finished = expected - len(scoring.missing(check.expected_standard_ids, [_as_result(e) for e in commit_results(check)]))
    return CommitState(INCOMPLETE, expected, finished)


def project_scores(projects) -> dict:
    """Each project's score (project id -> CommitScore), read in one query,
    with the scored results prefetched."""
    projects = list(projects)
    default_branch = {p.pk: p.default_branch for p in projects}
    scores = _newest_first(
        CommitScore.objects.filter(project__in=projects).select_related("commit_check")
    ).prefetch_related("executions")
    picked = {}
    for score in scores:
        if score.branch == default_branch[score.project_id]:
            picked.setdefault(score.project_id, score)
    return picked


@dataclass(frozen=True)
class NewerCommit:
    """A commit newer than the scored one on the branch, not scored (yet)."""

    sha: str
    state: CommitState


def newer_commit(project, branch: str, score: CommitScore | None) -> NewerCommit | None:
    """The branch's newest checked commit when it is newer than ``score``'s
    and has no score of its own: still checking, or incomplete."""
    checks = CommitCheck.objects.filter(project=project, branch=branch).exclude(commit_sha="")
    newest = checks.order_by(Coalesce("committed_at", "created_at").desc(), F("created_at").desc()).first()
    if newest is None or (score and newest.commit_sha == score.commit_sha):
        return None
    if CommitScore.objects.filter(project=project, branch=branch, commit_sha=newest.commit_sha).exists():
        return None
    state = commit_state(project, newest.commit_sha, branch)
    return NewerCommit(newest.commit_sha, state) if state else None
