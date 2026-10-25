from __future__ import annotations

from app.domain.score_representation.score_bands import ScoreBands
from app.domain.score_representation.score_representation import ScoreRepresentation


class LetterScoreRepresentation(ScoreRepresentation):
    """A score as its band's letter (``ScoreBands``): A+ for a perfect 100,
    A from 90, B from 75, C from 60, D below. F is kept for a commit a
    Required standard failed: an F always means failed, never a low average
    (that is a D). A letter's colour is its health (``ScoreHealth``): A+ and
    A healthy, B to D need attention, F failed; a D is shaded orange."""

    SCALE_NAME = "Grade"

    def letter(self, value) -> str:
        return ScoreBands.of(value).letter

    def band_text(self, band) -> str:
        return band.letter

    def band_spoken(self, band) -> str:
        return f"Grade {band.letter}: score {band.range_text}"

    def text_for(self, value) -> str:
        return self.letter(value)

    def spoken_for(self, value) -> str:
        return f"Grade {self.letter(value)}, score {round(value)} out of 100"
