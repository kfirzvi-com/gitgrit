from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.health import CRITICAL, level_from_score
from app.domain.score_representation.represented_score import RepresentedScore


class ScoreRepresentation(ABC):
    """How any 0-100 score is shown, everywhere in GitGrit (strategy). Swap
    the one in use (``SCORE_REPRESENTATION``) to change every screen, the
    badge, the diagrams and the notifications at once."""

    def represent(self, value: int | float | None, *, failed: bool = False) -> RepresentedScore:
        """``value`` as it is shown; ``failed`` marks a commit score a
        Required standard failed (its value is 0)."""
        if value is None:
            return RepresentedScore(self.no_score_text(), self.tone(None, failed=False), "No score yet")
        return RepresentedScore(self.text(value), self.tone(value, failed=failed), self.spoken(value))

    def tone(self, value, *, failed: bool) -> str:
        """The colour band: critical when a Required standard failed, else
        by value (``app.domain.health.level_from_score``)."""
        return CRITICAL if failed else level_from_score(value)

    def no_score_text(self) -> str:
        return "—"

    @abstractmethod
    def text(self, value) -> str:
        """What the reader sees for a value."""

    @abstractmethod
    def spoken(self, value) -> str:
        """The same, in words."""
