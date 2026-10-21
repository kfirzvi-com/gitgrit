from __future__ import annotations

from app.domain.importance import Importance
from app.domain.scoring.score import Score
from app.domain.scoring.scoring_policy import ScoringPolicy
from app.domain.scoring.status import ERROR, FAILED


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
