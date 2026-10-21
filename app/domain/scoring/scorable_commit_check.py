from __future__ import annotations

from dataclasses import dataclass

from app.domain.scoring.commit_scoring_policy import CommitScoringPolicy
from app.domain.scoring.commit_scoring_policy_in_use import COMMIT_SCORING_POLICY
from app.domain.scoring.commit_scoring_state import CommitScoringState
from app.domain.scoring.expected_standards import ExpectedStandards
from app.domain.scoring.new_commit_score import NewCommitScore
from app.domain.scoring.standard_run_results_on_commit import StandardRunResultsOnCommit


@dataclass(frozen=True)
class ScorableCommitCheck:
    """One check of one commit, seen for scoring: the commit, the standards
    it expects, and whether any of its own runs is still going."""

    commit_sha: str
    expected_standards: ExpectedStandards
    has_running_runs: bool

    def new_commit_score(
        self,
        runs_on_commit: StandardRunResultsOnCommit,
        policy: CommitScoringPolicy = COMMIT_SCORING_POLICY,
    ) -> NewCommitScore | None:
        """The commit's new score, or None when the check gives none: it has
        no commit, expects nothing, is still running, or the commit is
        incomplete (an expected standard has no finished run on it). The
        commit then keeps the score it had."""
        if not self.commit_sha or not self.expected_standards or self.has_running_runs:
            return None
        scored_from = runs_on_commit.newest_finished_per_expected_standard(self.expected_standards)
        if self.expected_standards.without_finished_result(scored_from):
            return None
        return NewCommitScore(policy.score_commit(scored_from), scored_from)

    def commit_scoring_state(
        self, runs_on_commit: StandardRunResultsOnCommit, *, any_run_going: bool, scored_by_this_check: bool
    ) -> CommitScoringState | None:
        """Where the commit stands when this is its newest check. None when
        the check expects nothing."""
        if not self.expected_standards:
            return None
        expected_count = len(self.expected_standards)
        finished_count = expected_count - len(
            self.expected_standards.without_finished_result(
                runs_on_commit.newest_finished_per_expected_standard(self.expected_standards)
            )
        )
        if any_run_going:
            return CommitScoringState(CommitScoringState.IN_PROGRESS, expected_count, finished_count)
        if scored_by_this_check:
            return CommitScoringState(CommitScoringState.COMPLETE, expected_count, expected_count)
        return CommitScoringState(CommitScoringState.INCOMPLETE, expected_count, finished_count)
