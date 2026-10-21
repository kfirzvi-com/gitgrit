from __future__ import annotations

from dataclasses import dataclass

from app.domain.scoring.check_outcome import CheckOutcome
from app.domain.scoring.commit_results import CommitResults
from app.domain.scoring.commit_state import CommitState
from app.domain.scoring.expectation import Expectation
from app.domain.scoring.policy import POLICY
from app.domain.scoring.scoring_policy import ScoringPolicy


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
