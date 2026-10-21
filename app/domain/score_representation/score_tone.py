from enum import StrEnum


class ScoreTone(StrEnum):
    """A score's colour band: the one list of them, mildest first. Project
    and stack health levels (``app.domain.health``) are these same tones."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CAUTION = "caution"
    CRITICAL = "critical"
    SEVERE = "severe"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        """What the band means, in words (diagram legends, tooltips)."""
        return {
            ScoreTone.HEALTHY: "Healthy",
            ScoreTone.WARNING: "Needs attention",
            ScoreTone.CAUTION: "At risk",
            ScoreTone.CRITICAL: "Critical",
            ScoreTone.SEVERE: "Failed",
            ScoreTone.UNKNOWN: "No data",
        }[self]

    @property
    def severity(self) -> int:
        """How bad the band is, for worst-of roll-ups: no data ranks lowest
        (a project with data always wins), a failed project highest."""
        return {
            ScoreTone.UNKNOWN: 0,
            ScoreTone.HEALTHY: 1,
            ScoreTone.WARNING: 2,
            ScoreTone.CAUTION: 3,
            ScoreTone.CRITICAL: 4,
            ScoreTone.SEVERE: 5,
        }[self]

    @property
    def needs_attention(self) -> bool:
        """Anything between healthy and no data."""
        return self not in (ScoreTone.HEALTHY, ScoreTone.UNKNOWN)

    @property
    def is_failing(self) -> bool:
        """Critical or worse."""
        return self in (ScoreTone.CRITICAL, ScoreTone.SEVERE)
