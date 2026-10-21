from __future__ import annotations

from app.domain.score_representation.score_representation import ScoreRepresentation
from app.domain.score_representation.score_tone import ScoreTone


class NumberScoreRepresentation(ScoreRepresentation):
    """A score as a whole number out of 100: "82". Healthy from 80, warning
    from 50, critical below; a score a Required standard failed is severe."""

    HEALTHY_MIN = 80
    WARNING_MIN = 50

    def text(self, value, *, failed: bool = False) -> str:
        return str(round(value))

    def tone(self, value, *, failed: bool = False) -> ScoreTone:
        if value is None:
            return ScoreTone.UNKNOWN
        if failed:
            return ScoreTone.SEVERE
        if value >= self.HEALTHY_MIN:
            return ScoreTone.HEALTHY
        if value >= self.WARNING_MIN:
            return ScoreTone.WARNING
        return ScoreTone.CRITICAL

    def spoken(self, value, *, failed: bool = False) -> str:
        return f"Score {round(value)} out of 100"
