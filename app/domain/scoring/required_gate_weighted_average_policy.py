from __future__ import annotations

from app.domain.importance import Importance
from app.domain.scoring.commit_score_value import CommitScoreValue
from app.domain.scoring.commit_scoring_policy import CommitScoringPolicy


class RequiredGateWeightedAveragePolicy(CommitScoringPolicy):
    """Nothing is reported until every expected standard has a result
    (passed or failed), in this order:

    1. any expected standard without a result, because it errored or never
       ran (of any importance, Required too): no score, even when a
       Required standard failed;
    2. a Required standard that failed fails the commit (F: a verdict, not
       a number);
    3. otherwise the average of the standards' own scores, weighted by
       importance."""

    # How much a standard's score counts toward the average. The one place
    # weights live.
    WEIGHT_BY_IMPORTANCE: dict[Importance, int] = {
        Importance.REQUIRED: 2,
        Importance.MAJOR: 2,
        Importance.MINOR: 1,
    }

    def score_commit(self, run_results, not_run=()) -> CommitScoreValue:
        finished = [r for r in run_results if r.is_finished]
        missing = [f"{r.standard_name} errored" for r in finished if r.errored]
        missing += [f"{name} not run" for name in not_run]
        if missing:
            return CommitScoreValue(None, reason=", ".join(missing))
        failing_required = [r for r in finished if r.fails_the_commit]
        if failing_required:
            names = ", ".join(r.standard_name for r in failing_required)
            return CommitScoreValue(None, failed_by_required_standard=True, reason=f"{names} failing")
        total_weight = sum(self.WEIGHT_BY_IMPORTANCE[r.importance] for r in finished)
        if not total_weight:
            return CommitScoreValue(None)
        weighted_sum = sum(r.standard_score * self.WEIGHT_BY_IMPORTANCE[r.importance] for r in finished)
        return CommitScoreValue(round(weighted_sum / total_weight))
