"""Project score: every rule about how a commit, a branch and a project are
scored. Pure, no I/O, no ORM; ``app.application.scoring`` loads the facts
and saves what these objects decide.

- ``Expectation`` (value object): the standards a check expects a finished
  result of, chosen from the project's ``Candidate`` standards.
- ``CommitResults`` (value object): every result on a commit; for an
  expectation, the newest finished result of each expected standard.
- ``ScoringPolicy`` (strategy): turns a complete commit's results into a
  ``Score``. ``RequiredGateWeightedAverage`` is the policy in use: a Required
  standard that failed or errored, for any reason, makes it 0; otherwise the
  average of the results' 0-100 scores weighted by importance, errors of
  other importances left out.
- ``Check`` (entity): one check of one commit; once finished and complete it
  scores its commit, and it says where the commit stands (``CommitState``).
- ``CommitTimeline``: how a branch's commits and scores are ordered, which
  score a commit keeps and which branch a commit is read on.

Each result carries the importance its standard had when it ran, so changing
importance or attachments later never rescores a commit.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.domain.importance import Importance

# Statuses as stored on ``StandardExecution.status``.
PASSED = "passed"
FAILED = "failed"
ERROR = "error"
RUNNING = "running"
FINISHED = (PASSED, FAILED, ERROR)


@dataclass(frozen=True)
class Result:
    """One standard's result on a commit. ``execution_id`` names the run it
    came from, so a score can say what it was computed from."""

    standard_id: str
    name: str
    status: str
    score: int
    importance: Importance = Importance.MAJOR
    execution_id: str = ""

    @property
    def finished(self) -> bool:
        return self.status in FINISHED

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


# --- What a check expects -----------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """A standard attached to a project, as a check considers it."""

    standard_id: str
    enabled: bool
    draft: bool
    # Its criteria (events, Branch/Tag Filter, languages) match the commit:
    # ``standard_criteria.applies``, which knows nothing of the standard's
    # lifecycle.
    matches_criteria: bool

    @property
    def applies(self) -> bool:
        """The standard runs on the commit: it is enabled, not a draft, and
        its criteria match."""
        return self.enabled and not self.draft and self.matches_criteria


@dataclass(frozen=True)
class Expectation:
    """The standards a check expects a finished result of (standard ids)."""

    standard_ids: tuple

    @classmethod
    def of(cls, candidates) -> "Expectation":
        """The candidates that apply to the commit."""
        return cls(tuple(str(c.standard_id) for c in candidates if c.applies))

    def __bool__(self) -> bool:
        return bool(self.standard_ids)

    def __len__(self) -> int:
        return len(self.standard_ids)

    def missing(self, results) -> list[str]:
        """The expected standards with no finished result among ``results``:
        empty when the commit is complete."""
        finished = {str(r.standard_id) for r in results if r.finished}
        return [str(i) for i in self.standard_ids if str(i) not in finished]


class CommitResults:
    """Every result on a commit, across all of its checks, newest first."""

    def __init__(self, newest_first):
        self._newest_first = list(newest_first)

    def for_expectation(self, expectation: Expectation) -> list[Result]:
        """The results the commit is scored from: for each expected standard,
        its newest finished result. A standard run again on the same commit
        replaces its earlier result."""
        wanted = {str(i) for i in expectation.standard_ids}
        picked = {}
        for result in self._newest_first:
            key = str(result.standard_id)
            if result.finished and key in wanted and key not in picked:
                picked[key] = result
        return list(picked.values())


# --- How results become a score -----------------------------------------------------


class ScoringPolicy(ABC):
    """How a complete commit's results become its score."""

    @abstractmethod
    def score(self, results) -> Score: ...


class RequiredGateWeightedAverage(ScoringPolicy):
    """A Required standard that failed or errored makes the commit 0;
    otherwise the importance-weighted average of the results, leaving out
    errors of other importances (an error says nothing about the code)."""

    # How much a result counts toward the average. The one place weights live.
    WEIGHTS: dict[Importance, int] = {
        Importance.REQUIRED: 2,
        Importance.MAJOR: 2,
        Importance.MINOR: 1,
    }

    def score(self, results) -> Score:
        results = [r for r in results if r.finished]
        failing = [r for r in results if r.fails_commit]
        if failing:
            return Score(0, failed=True, reason=self._reason(failing))
        counted = [r for r in results if r.status != ERROR]
        total_weight = sum(self.WEIGHTS[r.importance] for r in counted)
        if not total_weight:
            return Score(None)
        weighted = sum(r.score * self.WEIGHTS[r.importance] for r in counted)
        return Score(round(weighted / total_weight))

    @staticmethod
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


POLICY: ScoringPolicy = RequiredGateWeightedAverage()


# --- A check and its commit ---------------------------------------------------------


@dataclass(frozen=True)
class CheckOutcome:
    """A finished, complete check: the commit's new score and the results it
    was computed from."""

    score: Score
    results: list


@dataclass(frozen=True)
class CommitState:
    """Where a commit stands, by its newest check: ``complete`` (that check
    scored it), ``in_progress`` (a run on the commit is still going) or
    ``incomplete`` (it finished without every expected standard).
    ``expected`` and ``finished`` count that check's standards."""

    COMPLETE = "complete"
    IN_PROGRESS = "in_progress"
    INCOMPLETE = "incomplete"

    state: str
    expected: int
    finished: int


@dataclass(frozen=True)
class Check:
    """One check of one commit."""

    commit_sha: str
    expectation: Expectation
    # Any of the check's own runs not finished yet.
    running: bool

    def outcome(self, results: CommitResults, policy: ScoringPolicy = POLICY) -> CheckOutcome | None:
        """The commit's new score, or None when the check gives none: it has
        no commit, expects nothing, is still running, or the commit is
        incomplete (an expected standard has no finished result on it). The
        commit then keeps the score it had."""
        if not self.commit_sha or not self.expectation or self.running:
            return None
        scored_from = results.for_expectation(self.expectation)
        if self.expectation.missing(scored_from):
            return None
        return CheckOutcome(policy.score(scored_from), scored_from)

    def state(self, results: CommitResults, *, running: bool, scored: bool) -> CommitState | None:
        """Where the commit stands when this is its newest check, given
        whether any run on it is still going and whether this check
        ``scored`` it. None when the check expects nothing."""
        if not self.expectation:
            return None
        expected = len(self.expectation)
        finished = expected - len(self.expectation.missing(results.for_expectation(self.expectation)))
        if running:
            return CommitState(CommitState.IN_PROGRESS, expected, finished)
        if scored:
            return CommitState(CommitState.COMPLETE, expected, expected)
        return CommitState(CommitState.INCOMPLETE, expected, finished)


# --- A branch's commits -------------------------------------------------------------


class CommitTimeline:
    """How a branch's commits and scores are ordered. A branch shows its
    newest commit's score, never merely the newest run's: checking an old
    commit again must not replace a newer commit's score."""

    @staticmethod
    def ordered_at(committed_at: datetime | None, checked_at: datetime) -> datetime:
        """When a commit counts as made: its commit time, else when it was
        first checked."""
        return committed_at or checked_at

    @classmethod
    def newest(cls, checks):
        """The newest commit among a branch's checks (rows with
        ``commit_sha``, ``committed_at`` and ``created_at``), or None."""
        checked = [c for c in checks if c.commit_sha]
        if not checked:
            return None
        return max(checked, key=lambda c: (cls.ordered_at(c.committed_at, c.created_at), c.created_at))

    @staticmethod
    def last_score_per_commit(scores_newest_first) -> dict:
        """Each commit's score (sha -> score row): the last one it reached. A
        newer check replaces it only when it completes too, so a commit's
        newest score row is its score."""
        latest = {}
        for row in scores_newest_first:
            latest.setdefault(row.commit_sha, row)
        return latest

    @staticmethod
    def branch_of(score_branch: str | None, checked_branches_newest_first, default_branch: str) -> str:
        """The branch a commit is read on: the branch of its score, else the
        branch it was last checked on, else the project's default branch."""
        if score_branch:
            return score_branch
        return next(iter(checked_branches_newest_first), default_branch)
