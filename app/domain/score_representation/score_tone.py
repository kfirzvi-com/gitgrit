from enum import StrEnum


class ScoreTone(StrEnum):
    """A score's colour band: the one list of them. Project and stack health
    levels (``app.domain.health``) are these same tones."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        """What the band means, in words (diagram legends, tooltips)."""
        return {
            ScoreTone.HEALTHY: "Healthy",
            ScoreTone.WARNING: "Needs attention",
            ScoreTone.CRITICAL: "Critical",
            ScoreTone.UNKNOWN: "No data",
        }[self]
