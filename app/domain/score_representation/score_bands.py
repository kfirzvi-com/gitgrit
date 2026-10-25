from __future__ import annotations

from app.domain.score_representation.score_band import ScoreBand


class ScoreBands:
    """The one scale every 0-100 commit score falls on, best first: A+ 100,
    A 90-99, B 75-89, C 60-74, D 0-59. Letters show a band's letter, numbers
    its range: one-to-one, so both read the same categories. (A failed
    commit is no band: it reads F either way.)"""

    BANDS = (
        ScoreBand("A+", 100, 100),
        ScoreBand("A", 90, 99),
        ScoreBand("B", 75, 89),
        ScoreBand("C", 60, 74),
        ScoreBand("D", 0, 59),
    )
    # The lowest band is painted apart (orange): it still needs attention.
    LOW_SHADE = "low"
    # The bands that are healthy (``ScoreHealth``): A and better.
    HEALTHY_DOWN_TO = "A"

    @classmethod
    def healthy_from(cls) -> int:
        return next(band.lowest for band in cls.BANDS if band.letter == cls.HEALTHY_DOWN_TO)

    @classmethod
    def of(cls, value) -> ScoreBand:
        rounded = round(value)
        return next((band for band in cls.BANDS if band.covers(rounded)), cls.BANDS[-1])

    @classmethod
    def lowest(cls) -> ScoreBand:
        return cls.BANDS[-1]

    @classmethod
    def shade_of(cls, value) -> str:
        """``LOW_SHADE`` for a score in the lowest band; "" (its tone's) else."""
        return cls.LOW_SHADE if cls.of(value) == cls.lowest() else ""
