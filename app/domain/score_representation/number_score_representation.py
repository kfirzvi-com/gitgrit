from __future__ import annotations

from app.domain.score_representation.score_representation import ScoreRepresentation


class NumberScoreRepresentation(ScoreRepresentation):
    """A score as a whole number out of 100: "82", painted like its band's
    letter (a score below 60 orange, like a D). A failed commit reads F, as
    in every representation. Its scale is the bands as numbers: 100, 90–99,
    75–89, 60–74, 0–59, F."""

    def band_text(self, band) -> str:
        return band.range_text

    def band_spoken(self, band) -> str:
        return f"Score {band.range_text} (grade {band.letter})"

    def text_for(self, value) -> str:
        return str(round(value))

    def spoken_for(self, value) -> str:
        return f"Score {round(value)} out of 100"
