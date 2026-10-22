from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.score_representation.represented_score import RepresentedScore
from app.domain.score_representation.score_health import ScoreHealth
from app.domain.score_representation.score_tone import ScoreTone


class ScoreRepresentation(ABC):
    """How a 0-100 score reads (strategy). GitGrit uses one for commit scores
    (``COMMIT_SCORE_REPRESENTATION``) and one for a standard's result
    (``STANDARD_RESULT_REPRESENTATION``); swapping either changes every screen,
    badge, diagram, notification and API ``display`` that shows that kind of
    score at once. Whatever the representation, a score's health (its tone,
    its colour) comes from ``ScoreHealth``."""

    def represent(self, value: int | float | None, *, failed: bool = False) -> RepresentedScore:
        """``value`` as it is shown; ``failed`` marks a commit a Required
        standard failed, which reads as failed whatever its value."""
        if failed:
            return RepresentedScore(self.failed_text(), ScoreTone.FAILED, self.failed_spoken())
        if value is None:
            return RepresentedScore(self.no_score_text(), ScoreTone.UNKNOWN, "No score yet")
        return RepresentedScore(self.text_for(value), ScoreHealth.tone(value), self.spoken_for(value))

    def tone(self, value, *, failed: bool = False) -> ScoreTone:
        return ScoreHealth.tone(value, failed=failed)

    def no_score_text(self) -> str:
        return "—"

    def scale(self) -> list[tuple[str, ScoreTone]]:
        """Every value this representation can show, best first, with its
        tone: what a scale of it (the Overview's grade row) lists. Empty
        when it has no short scale (numbers)."""
        return []

    @abstractmethod
    def text_for(self, value) -> str:
        """What the reader sees for a score."""

    @abstractmethod
    def spoken_for(self, value) -> str:
        """The same, in words."""

    @abstractmethod
    def failed_text(self) -> str:
        """What a failed commit reads as."""

    @abstractmethod
    def failed_spoken(self) -> str:
        """The same, in words."""
