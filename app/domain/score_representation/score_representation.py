from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.score_representation.represented_score import RepresentedScore
from app.domain.score_representation.score_tone import ScoreTone


class ScoreRepresentation(ABC):
    """How any 0-100 score is shown, everywhere in GitGrit (strategy). Swap
    the one in use (``SCORE_REPRESENTATION``) to change every screen, the
    badge, the diagrams, the notifications and the API's ``display`` at once.
    Each representation also decides a score's band (``tone``): the one place
    a score becomes a colour."""

    def represent(self, value: int | float | None, *, failed: bool = False) -> RepresentedScore:
        """``value`` as it is shown; ``failed`` marks a commit score a
        Required standard failed (its value is 0)."""
        if value is None:
            return RepresentedScore(self.no_score_text(), ScoreTone.UNKNOWN, "No score yet")
        return RepresentedScore(
            self.text(value, failed=failed), self.tone(value, failed=failed), self.spoken(value, failed=failed)
        )

    def no_score_text(self) -> str:
        return "—"

    @abstractmethod
    def text(self, value, *, failed: bool = False) -> str:
        """What the reader sees for a value."""

    @abstractmethod
    def tone(self, value, *, failed: bool = False) -> ScoreTone:
        """The value's band; ``UNKNOWN`` for None."""

    @abstractmethod
    def spoken(self, value, *, failed: bool = False) -> str:
        """The same, in words."""
