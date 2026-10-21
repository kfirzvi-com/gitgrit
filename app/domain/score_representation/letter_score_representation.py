from __future__ import annotations

from app.domain.score_representation.score_representation import ScoreRepresentation
from app.domain.score_representation.score_tone import ScoreTone


class LetterScoreRepresentation(ScoreRepresentation):
    """A score as a letter: A+ for a perfect 100, A from 90, B from 75, C
    from 60, D below. F is kept for a score a Required standard failed: an F
    always means the project failed, never just a low average. The value
    underneath (and the API's numbers) never change."""

    # (lowest score, letter), best first; below the last band is a D.
    BANDS = ((100, "A+"), (90, "A"), (75, "B"), (60, "C"))
    LOWEST = "D"
    FAILED = "F"

    # Each letter's band: the one place letters get their colours' meaning.
    TONE_BY_LETTER = {
        "A+": ScoreTone.HEALTHY,
        "A": ScoreTone.HEALTHY,
        "B": ScoreTone.WARNING,
        "C": ScoreTone.CAUTION,
        "D": ScoreTone.CRITICAL,
        "F": ScoreTone.SEVERE,
    }

    def letter(self, value, *, failed: bool = False) -> str:
        if failed:
            return self.FAILED
        for lowest, letter in self.BANDS:
            if value >= lowest:
                return letter
        return self.LOWEST

    def text(self, value, *, failed: bool = False) -> str:
        return self.letter(value, failed=failed)

    def tone(self, value, *, failed: bool = False) -> ScoreTone:
        if value is None:
            return ScoreTone.UNKNOWN
        return self.TONE_BY_LETTER[self.letter(value, failed=failed)]

    def spoken(self, value, *, failed: bool = False) -> str:
        letter = self.letter(value, failed=failed)
        if failed:
            return "Grade F: a Required standard failed"
        return f"Grade {letter}, score {round(value)} out of 100"
