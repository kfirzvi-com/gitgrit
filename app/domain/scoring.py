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
"""
from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class Result:
    """One standard's finished result on a commit."""

    standard_id: str
    name: str
    status: str
    score: int
    importance: Importance = Importance.MAJOR

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
