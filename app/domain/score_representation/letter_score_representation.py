from __future__ import annotations

from app.domain.score_representation.represented_score import RepresentedScore
from app.domain.score_representation.score_representation import ScoreRepresentation


class LetterScoreRepresentation(ScoreRepresentation):
    """A score as a letter: A+ for a perfect 100, A from 90, B from 75, C
    from 60, D below. F is kept for a commit a Required standard failed: an
    F always means failed, never a low average (that is a D). A letter's
    colour is its health (``ScoreHealth``): A+ and A healthy, B to D need
    attention, F failed; a D is shaded orange (``LOW_SHADE``), apart from B
    and C, though it needs attention just the same."""

    # (lowest score, letter), best first; below the last band is a D.
    BANDS = ((100, "A+"), (90, "A"), (75, "B"), (60, "C"))
    LOWEST = "D"
    FAILED = "F"
    LOW_SHADE = "low"

    def letter(self, value) -> str:
        for lowest, letter in self.BANDS:
            if value >= lowest:
                return letter
        return self.LOWEST

    def scale(self) -> list[RepresentedScore]:
        """A+ to F, each as it is shown."""
        return [self.represent(lowest) for lowest, _ in self.BANDS] + [
            self.represent(0),
            self.represent(None, failed=True),
        ]

    def shade_for(self, value) -> str:
        return self.LOW_SHADE if self.letter(value) == self.LOWEST else ""

    def text_for(self, value) -> str:
        return self.letter(value)

    def spoken_for(self, value) -> str:
        return f"Grade {self.letter(value)}, score {round(value)} out of 100"

    def failed_text(self) -> str:
        return self.FAILED

    def failed_spoken(self) -> str:
        return "Grade F: a Required standard failed"
