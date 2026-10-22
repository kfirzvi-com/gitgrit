from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.scoring.commit_score_outcome import CommitScoreOutcome
from app.domain.scoring.commit_score_value import CommitScoreValue
from app.domain.scoring.commit_scoring_policy import CommitScoringPolicy
from app.domain.scoring.commit_scoring_policy_in_use import COMMIT_SCORING_POLICY
from app.domain.scoring.commit_standing import CommitStanding
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
        standard_names: Mapping[str, str] | None = None,
        policy: CommitScoringPolicy = COMMIT_SCORING_POLICY,
    ) -> NewCommitScore | None:
        """The commit's score once this check is done, from each expected
        standard's newest finished run on the commit (across its checks).
        None while there is nothing to decide: the check has no commit
        yet, expects nothing, or one of its runs is still going. Otherwise
        always a score, no score included: an expected standard with no
        finished run is "not run" (named by ``standard_names``, standard
        id to name)."""
        if not self.commit_sha or not self.expected_standards or self.has_running_runs:
            return None
        scored_from = runs_on_commit.newest_finished_per_expected_standard(self.expected_standards)
        names = standard_names or {}
        not_run = [names.get(i, i) for i in self.expected_standards.without_finished_result(scored_from)]
        return NewCommitScore(policy.score_commit(scored_from, not_run), scored_from)

    def standing(
        self,
        runs_on_commit: StandardRunResultsOnCommit,
        *,
        any_run_going: bool,
        saved: CommitScoreValue | None,
        standard_names: Mapping[str, str] | None = None,
    ) -> CommitStanding | None:
        """Where the commit stands when this is its newest check: checking
        while any run on the commit is going; otherwise the score this check
        saved (``saved``), or, for a check that saved none, the one it
        gives now. None when the check expects nothing or has no commit."""
        if not self.expected_standards:
            return None
        expected_count = len(self.expected_standards)
        finished_count = expected_count - len(
            self.expected_standards.without_finished_result(
                runs_on_commit.newest_finished_per_expected_standard(self.expected_standards)
            )
        )
        going = any_run_going or self.has_running_runs
        if saved is None and not going:
            new_score = self.new_commit_score(runs_on_commit, standard_names)
            saved = new_score.score if new_score else None
        outcome = CommitScoreOutcome.of_commit(going, saved.outcome if saved else None)
        if outcome is None:
            return None
        if outcome is CommitScoreOutcome.CHECKING:
            return CommitStanding(outcome, "", expected_count, finished_count)
        return CommitStanding(outcome, saved.reason, expected_count, finished_count, saved.value)
