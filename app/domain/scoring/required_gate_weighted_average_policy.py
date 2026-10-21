from __future__ import annotations

from app.domain.importance import Importance
from app.domain.scoring.commit_score_value import CommitScoreValue
from app.domain.scoring.commit_scoring_policy import CommitScoringPolicy
from app.domain.scoring.standard_run_status import StandardRunStatus


class RequiredGateWeightedAveragePolicy(CommitScoringPolicy):
    """A Required standard that failed or errored, for any reason, makes the
    commit 0; otherwise the commit's score is the average of the standards'
    own scores weighted by importance, leaving out errored runs of other
    importances (an error says nothing about the code)."""

    # How much a standard's score counts toward the average. The one place
    # weights live.
    WEIGHT_BY_IMPORTANCE: dict[Importance, int] = {
        Importance.REQUIRED: 2,
        Importance.MAJOR: 2,
        Importance.MINOR: 1,
    }

    def score_commit(self, run_results) -> CommitScoreValue:
        finished = [r for r in run_results if r.is_finished]
        failing_required = [r for r in finished if r.fails_the_commit]
        if failing_required:
            return CommitScoreValue(
                0,
                failed_by_required_standard=True,
                failure_reason=self._failure_reason(failing_required),
            )
        averaged = [r for r in finished if r.status != StandardRunStatus.ERROR]
        total_weight = sum(self.WEIGHT_BY_IMPORTANCE[r.importance] for r in averaged)
        if not total_weight:
            return CommitScoreValue(None)
        weighted_sum = sum(r.standard_score * self.WEIGHT_BY_IMPORTANCE[r.importance] for r in averaged)
        return CommitScoreValue(round(weighted_sum / total_weight))

    @staticmethod
    def _failure_reason(failing_required) -> str:
        """"No secrets failing; could not verify License" — failed ones first."""
        failed = [r.standard_name for r in failing_required if r.status == StandardRunStatus.FAILED]
        errored = [r.standard_name for r in failing_required if r.status == StandardRunStatus.ERROR]
        parts = []
        if failed:
            parts.append(f"{', '.join(failed)} failing")
        if errored:
            parts.append(f"could not verify {', '.join(errored)}")
        return "; ".join(parts)
