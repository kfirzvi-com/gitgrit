"""Project score: the rule that turns one commit's results into a score.
Pure, no I/O, no ORM.

A commit is scored once it is complete: every standard expected on it (the
attached, runnable standards when its check was queued) has a finished
result. Then:

- a Required standard that failed or errored, for any reason, GitGrit's own
  failures included, fails the commit: its score is 0;
- otherwise the score is the average of the results' 0-100 scores, weighted
  by each result's importance (``WEIGHTS``). Errored results of other
  importances are left out: an error says nothing about the code.

Each result carries the importance its standard had when it ran, so changing
importance or attachments later never rescores a commit.

Beyond the score itself this module holds every rule about commit scores:
which standards a check expects (``expected``), which results a commit is
scored from (``newest_per_standard``), when a finished check scores its
commit (``score_check``), which score a commit and a branch show
(``latest_per_commit``, ``ordered_at``), a commit's state (``commit_state``)
and which branch a commit is read on (``commit_branch``). Callers pass plain
facts or rows; nothing here reads or writes the database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.importance import Importance

# How much a result counts toward the average. The one place weights live.
WEIGHTS: dict[Importance, int] = {
    Importance.REQUIRED: 2,
    Importance.MAJOR: 2,
    Importance.MINOR: 1,
}

# Statuses as stored on ``StandardExecution.status``.
PASSED = "passed"
FAILED = "failed"
ERROR = "error"
FINISHED = (PASSED, FAILED, ERROR)


RUNNING = "running"


@dataclass(frozen=True)
class Candidate:
    """A standard attached to a project, as a check considers it."""

    standard_id: str
    enabled: bool
    draft: bool
    # Its criteria match the commit (``standard_criteria.applies``).
    applies: bool


def expected(candidates) -> list[str]:
    """The standards a check expects a finished result of: attached,
    enabled, not a draft, and applying to the commit."""
    return [str(c.standard_id) for c in candidates if c.enabled and not c.draft and c.applies]


@dataclass(frozen=True)
class Result:
    """One standard's result on a commit. ``execution_id`` names the run
    it came from, so a score can say what it was computed from."""

    standard_id: str
    name: str
    status: str
    score: int
    importance: Importance = Importance.MAJOR
    execution_id: str = ""

    @property
    def fails_commit(self) -> bool:
        """A Required standard that did not pass."""
        return self.importance is Importance.REQUIRED and self.status in (FAILED, ERROR)


@dataclass(frozen=True)
class Score:
    """A complete commit's score. ``value`` is None when no result could be
    averaged (every one errored); ``reason`` says why a failed commit is 0."""

    value: int | None
    failed: bool = False
    reason: str = ""


def newest_per_standard(expected_ids, results_newest_first) -> list[Result]:
    """The results a commit is scored from: for each expected standard, its
    newest finished result across all of the commit's checks. A standard run
    again on the same commit replaces its earlier result."""
    wanted = {str(i) for i in expected_ids}
    picked = {}
    for result in results_newest_first:
        key = str(result.standard_id)
        if result.status in FINISHED and key in wanted and key not in picked:
            picked[key] = result
    return list(picked.values())


def missing(expected_ids, results) -> list[str]:
    """The expected standards with no finished result: empty when the
    commit is complete."""
    finished = {str(r.standard_id) for r in results if r.status in FINISHED}
    return [str(i) for i in expected_ids if str(i) not in finished]


def score(results) -> Score:
    """The score of a complete commit's results (see the module docstring)."""
    results = [r for r in results if r.status in FINISHED]
    failing = [r for r in results if r.fails_commit]
    if failing:
        return Score(0, failed=True, reason=_reason(failing))
    counted = [r for r in results if r.status != ERROR]
    total_weight = sum(WEIGHTS[r.importance] for r in counted)
    if not total_weight:
        return Score(None)
    weighted = sum(r.score * WEIGHTS[r.importance] for r in counted)
    return Score(round(weighted / total_weight))


def _reason(failing) -> str:
    """"No secrets failing; could not verify License" — failed ones first."""
    failed = [r.name for r in failing if r.status == FAILED]
    errored = [r.name for r in failing if r.status == ERROR]
    parts = []
    if failed:
        parts.append(f"{', '.join(failed)} failing")
    if errored:
        parts.append(f"could not verify {', '.join(errored)}")
    return "; ".join(parts)


# --- A check and its commit -------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One check of one commit, as scoring needs it."""

    commit_sha: str
    expected_ids: tuple
    # Any of the check's own runs not finished yet.
    running: bool


@dataclass(frozen=True)
class CheckOutcome:
    """A finished, complete check: the commit's new score and the results it
    was computed from."""

    score: Score
    results: list


def score_check(check: Check, results_newest_first) -> CheckOutcome | None:
    """Score ``check``'s commit, or None when it gives no new score: the
    check has no commit, expects nothing, is still running, or the commit is
    incomplete (an expected standard has no finished result on it). The
    commit then keeps the score it had."""
    if not check.commit_sha or not check.expected_ids or check.running:
        return None
    results = newest_per_standard(check.expected_ids, results_newest_first)
    if missing(check.expected_ids, results):
        return None
    return CheckOutcome(score(results), results)


def ordered_at(committed_at: datetime | None, checked_at: datetime) -> datetime:
    """When a commit counts as made, to order a branch's commits: its commit
    time, else when it was first checked. A branch shows its newest commit's
    score, never merely the newest run's: checking an old commit again must
    not replace a newer commit's score."""
    return committed_at or checked_at


def latest_per_commit(scores_newest_first) -> dict:
    """Each commit's score (sha -> score): the last one it reached. A newer
    check replaces it only when it completes too, so a commit's newest score
    row is its score. Rows need ``commit_sha``."""
    latest = {}
    for row in scores_newest_first:
        latest.setdefault(row.commit_sha, row)
    return latest


COMPLETE, IN_PROGRESS, INCOMPLETE = "complete", "in_progress", "incomplete"


@dataclass(frozen=True)
class CommitState:
    """Where a commit stands, by its newest check: ``complete`` (that check
    scored it), ``in_progress`` (a run on the commit is still going) or
    ``incomplete`` (it finished without every expected standard).
    ``expected`` and ``finished`` count that check's standards."""

    state: str
    expected: int
    finished: int


def commit_state(newest: Check, results_newest_first, *, running: bool, scored: bool) -> CommitState | None:
    """The state of a commit from its ``newest`` check, its results, whether
    any run on it is still going and whether that check ``scored`` it. None
    when the check expects nothing."""
    if not newest.expected_ids:
        return None
    expected_count = len(newest.expected_ids)
    finished = expected_count - len(
        missing(newest.expected_ids, newest_per_standard(newest.expected_ids, results_newest_first))
    )
    if running:
        return CommitState(IN_PROGRESS, expected_count, finished)
    if scored:
        return CommitState(COMPLETE, expected_count, expected_count)
    return CommitState(INCOMPLETE, expected_count, finished)


def newest_commit(checks) -> object | None:
    """The newest commit among a branch's checks (by ``ordered_at`` of each
    check's ``committed_at`` and ``created_at``, then the newest check).
    Rows need ``commit_sha``, ``committed_at`` and ``created_at``."""
    checked = [c for c in checks if c.commit_sha]
    if not checked:
        return None
    return max(checked, key=lambda c: (ordered_at(c.committed_at, c.created_at), c.created_at))


def commit_branch(score_branch: str | None, checked_branches_newest_first, default_branch: str) -> str:
    """The branch a commit is read on: the branch of its score, else the
    branch it was last checked on, else the project's default branch."""
    if score_branch:
        return score_branch
    return next(iter(checked_branches_newest_first), default_branch)
