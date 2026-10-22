from __future__ import annotations

from app.domain.score_representation.score_health import ScoreHealth
from app.domain.score_representation.score_representation import ScoreRepresentation
from app.domain.score_representation.score_tone import ScoreTone


class LetterScoreRepresentation(ScoreRepresentation):
    """A score as a letter: A+ for a perfect 100, A from 90, B from 75, C
    from 60, D below. F is kept for a commit a Required standard failed: an
    F always means failed, never a low average (that is a D). A letter's
    colour is its health (``ScoreHealth``): A+ and A healthy, B to D need
    attention, F failed."""

    # (lowest score, letter), best first; below the last band is a D.
    BANDS = ((100, "A+"), (90, "A"), (75, "B"), (60, "C"))
    LOWEST = "D"
    FAILED = "F"

    def letter(self, value) -> str:
        for lowest, letter in self.BANDS:
            if value >= lowest:
                return letter
        return self.LOWEST

    def scale(self) -> list[tuple[str, ScoreTone]]:
        """A+ to F, each with its health."""
        scored = [(letter, ScoreHealth.tone(lowest)) for lowest, letter in self.BANDS]
        return scored + [(self.LOWEST, ScoreHealth.tone(0)), (self.FAILED, ScoreTone.FAILED)]

    def text_for(self, value) -> str:
        return self.letter(value)

    def spoken_for(self, value) -> str:
        return f"Grade {self.letter(value)}, score {round(value)} out of 100"

    def failed_text(self) -> str:
        return self.FAILED

    def failed_spoken(self) -> str:
        return "Grade F: a Required standard failed"
