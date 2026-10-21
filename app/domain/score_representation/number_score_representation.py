from __future__ import annotations

from app.domain.score_representation.score_representation import ScoreRepresentation


class NumberScoreRepresentation(ScoreRepresentation):
    """A score as a whole number out of 100: "82"."""

    def text(self, value) -> str:
        return str(round(value))

    def spoken(self, value) -> str:
        return f"Score {round(value)} out of 100"
