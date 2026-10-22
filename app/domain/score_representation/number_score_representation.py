from __future__ import annotations

from app.domain.score_representation.score_representation import ScoreRepresentation


class NumberScoreRepresentation(ScoreRepresentation):
    """A score as a whole number out of 100: "82". A commit a Required
    standard failed reads "Failed"."""

    def text_for(self, value) -> str:
        return str(round(value))

    def spoken_for(self, value) -> str:
        return f"Score {round(value)} out of 100"

    def failed_text(self) -> str:
        return "Failed"

    def failed_spoken(self) -> str:
        return "Failed: a Required standard failed"
