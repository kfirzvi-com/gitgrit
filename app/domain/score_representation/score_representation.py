from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.score_representation.represented_score import RepresentedScore
from app.domain.score_representation.score_tone import ScoreTone


class ScoreRepresentation(ABC):
    """How any 0-100 score is shown, everywhere in GitGrit (strategy). Swap
    the one in use (``SCORE_REPRESENTATION``) to change every screen, the
    badge, the diagrams, the notifications and the API's ``display`` at once.
    The tone thresholds live here too: the one place a score becomes a band."""

    # A score at or above this is healthy; at or above WARNING_MIN, warning;
    # below, critical.
    HEALTHY_MIN = 80
    WARNING_MIN = 50

    def represent(self, value: int | float | None, *, failed: bool = False) -> RepresentedScore:
        """``value`` as it is shown; ``failed`` marks a commit score a
        Required standard failed (its value is 0)."""
        if value is None:
            return RepresentedScore(self.no_score_text(), ScoreTone.UNKNOWN, "No score yet")
        return RepresentedScore(self.text(value), self.tone(value, failed=failed), self.spoken(value))

    def tone(self, value: int | float | None, *, failed: bool = False) -> ScoreTone:
        """The band: critical when a Required standard failed, else by value."""
        if value is None:
            return ScoreTone.UNKNOWN
        if failed:
            return ScoreTone.CRITICAL
        if value >= self.HEALTHY_MIN:
            return ScoreTone.HEALTHY
        if value >= self.WARNING_MIN:
            return ScoreTone.WARNING
        return ScoreTone.CRITICAL

    def no_score_text(self) -> str:
        return "—"

    @abstractmethod
    def text(self, value) -> str:
        """What the reader sees for a value."""

    @abstractmethod
    def spoken(self, value) -> str:
        """The same, in words."""
