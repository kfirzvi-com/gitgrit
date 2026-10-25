from __future__ import annotations

from app.domain.score_representation.score_bands import ScoreBands
from app.domain.score_representation.score_tone import ScoreTone


class ScoreHealth:
    """The one rule that turns a score into health, for every 0-100 score
    GitGrit shows: healthy from ``HEALTHY_FROM``, needs attention below it,
    failed only when a Required standard failed (whatever the number), and
    unknown with no score. A low score is never "failed"."""

    # Healthy is an A or better: the threshold is the A band's (ScoreBands),
    # so health and the scale cannot drift apart.
    HEALTHY_FROM = ScoreBands.healthy_from()

    @classmethod
    def tone(cls, value, *, failed: bool = False) -> ScoreTone:
        if failed:
            return ScoreTone.FAILED
        if value is None:
            return ScoreTone.UNKNOWN
        return ScoreTone.HEALTHY if value >= cls.HEALTHY_FROM else ScoreTone.NEEDS_ATTENTION
