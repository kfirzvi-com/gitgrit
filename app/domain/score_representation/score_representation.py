from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.score_representation.represented_score import RepresentedScore
from app.domain.score_representation.score_bands import ScoreBands
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
        return RepresentedScore(
            self.text_for(value), ScoreHealth.tone(value), self.spoken_for(value), self.shade_for(value)
        )

    def shade_for(self, value) -> str:
        """The colour a score is painted in: its tone's (""), or orange in the
        lowest band (``ScoreBands``), the same however it reads."""
        return ScoreBands.shade_of(value)

    def tone(self, value, *, failed: bool = False) -> ScoreTone:
        return ScoreHealth.tone(value, failed=failed)

    def no_score_text(self) -> str:
        return "—"

    # What the scale (the Overview's row above the score) is called.
    SCALE_NAME = "Score"

    def scale(self) -> list[RepresentedScore]:
        """The steps a score can fall in, best first, each in its colour: one
        per band (``ScoreBands``) and F. Built here, from the bands, so every
        representation has the same categories in the same order and colours:
        a representation only says how a band is written (``band_text``)."""
        steps = [
            RepresentedScore(
                self.band_text(band), ScoreHealth.tone(band.lowest), self.band_spoken(band), ScoreBands.shade_of(band.lowest)
            )
            for band in ScoreBands.BANDS
        ]
        return steps + [self.represent(None, failed=True)]

    def scale_step_of(self, value, *, failed: bool = False) -> str:
        """The scale step ``value`` falls in (the one the row lights up)."""
        if failed:
            return self.failed_text()
        return "" if value is None else self.band_text(ScoreBands.of(value))

    @abstractmethod
    def band_text(self, band) -> str:
        """How a band (``ScoreBand``) is written on the scale: "B", "75–89"."""

    @abstractmethod
    def band_spoken(self, band) -> str:
        """The same, in words."""

    @abstractmethod
    def text_for(self, value) -> str:
        """What the reader sees for a score."""

    @abstractmethod
    def spoken_for(self, value) -> str:
        """The same, in words."""

    # A failed commit is a verdict, not a score: it reads the same however
    # a workspace shows scores.
    FAILED_TEXT = "F"
    FAILED_SPOKEN = "Failed: a Required standard failed"

    def failed_text(self) -> str:
        """What a failed commit reads as, in every representation."""
        return self.FAILED_TEXT

    def failed_spoken(self) -> str:
        return self.FAILED_SPOKEN
