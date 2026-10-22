from __future__ import annotations

from enum import StrEnum

from app.domain.score_representation.letter_score_representation import LetterScoreRepresentation
from app.domain.score_representation.number_score_representation import NumberScoreRepresentation
from app.domain.score_representation.score_representation import ScoreRepresentation


class ScoreDisplay(StrEnum):
    """How a workspace prefers to show a commit's score (and so a branch's
    and a project's): as a letter or as a number. A preference only: the
    score, its health, its colours and the API's numbers are the same
    either way, and a standard's own result is always a number."""

    LETTERS = "letters"
    NUMBERS = "numbers"

    @property
    def label(self) -> str:
        return {ScoreDisplay.LETTERS: "Letters (A+ to F)", ScoreDisplay.NUMBERS: "Numbers (0 to 100)"}[self]

    @property
    def example(self) -> str:
        return {ScoreDisplay.LETTERS: "B · F", ScoreDisplay.NUMBERS: "82 · Failed"}[self]

    @property
    def representation(self) -> ScoreRepresentation:
        return _REPRESENTATIONS[self]

    @classmethod
    def of(cls, preference) -> "ScoreDisplay":
        """A stored preference (a workspace's ``score_display``), or the
        default (letters) when there is none or it is unknown."""
        return cls(preference) if preference in set(cls) else cls.LETTERS


_REPRESENTATIONS = {
    ScoreDisplay.LETTERS: LetterScoreRepresentation(),
    ScoreDisplay.NUMBERS: NumberScoreRepresentation(),
}
