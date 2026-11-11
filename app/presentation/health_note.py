from __future__ import annotations

from app.domain.scoring import CommitScoreOutcome
from app.presentation.no_score_note import NO_RESULT

NOT_CHECKED = "Not checked yet"


class HealthNote:
    """Why a project shows the health it does, in a few words, beside its
    grade: the grade alone says enough for a scored commit; a failed one
    names what failed; one with no score says what is missing; one never
    checked says so. Used where a list shows many projects' health at once
    (a stack's components)."""

    @staticmethod
    def text(score) -> str:
        """``score``: the project's CommitScore, or None when it has none."""
        if score is None:
            return NOT_CHECKED
        if score.outcome is CommitScoreOutcome.NO_SCORE:
            return f"No score: {score.reason or NO_RESULT}"
        if score.failed:
            return score.reason
        return ""
