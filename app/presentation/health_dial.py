from __future__ import annotations

from dataclasses import dataclass

from app.domain.score_representation import ScoreTone

GAP = 1  # percent of the arc between segments


@dataclass(frozen=True)
class DialSegment:
    tone: ScoreTone
    start: float  # percent of the arc
    length: float


class HealthDial:
    """The dashboard's centre dial: one arc split into failed, needs
    attention and healthy, each as long as its share of the projects. Counts
    only: never one grade or colour for the workspace."""

    ORDER = (ScoreTone.FAILED, ScoreTone.NEEDS_ATTENTION, ScoreTone.HEALTHY)

    @classmethod
    def segments(cls, counts) -> list[DialSegment]:
        """``counts``: a ProjectHealthCounts."""
        values = {
            ScoreTone.FAILED: counts.failed,
            ScoreTone.NEEDS_ATTENTION: counts.needs_attention,
            ScoreTone.HEALTHY: counts.healthy,
        }
        shown = [(tone, values[tone]) for tone in cls.ORDER if values[tone]]
        total = sum(n for _, n in shown)
        if not total:
            return []
        room = 100 - GAP * (len(shown) - 1)
        segments, start = [], 0.0
        for tone, n in shown:
            length = round(room * n / total, 2)
            segments.append(DialSegment(tone=tone, start=round(start, 2), length=length))
            start += length + GAP
        return segments
