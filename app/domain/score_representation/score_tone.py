from enum import StrEnum


class ScoreTone(StrEnum):
    """A score's health: the one list of them, mildest first. A project's
    health (``app.domain.health``) is one of these tones, and
    ``ScoreHealth`` is the one rule that puts a score in one."""

    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"
    FAILED = "failed"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        """What the tone means, in words (legends, tooltips)."""
        return {
            ScoreTone.HEALTHY: "Healthy",
            ScoreTone.NEEDS_ATTENTION: "Needs attention",
            ScoreTone.FAILED: "Failed",
            ScoreTone.UNKNOWN: "No data",
        }[self]

    @property
    def severity(self) -> int:
        """How bad the tone is, for worst-of roll-ups: no data ranks lowest
        (a project with data always wins), a failed project highest."""
        return {
            ScoreTone.UNKNOWN: 0,
            ScoreTone.HEALTHY: 1,
            ScoreTone.NEEDS_ATTENTION: 2,
            ScoreTone.FAILED: 3,
        }[self]

    @property
    def needs_attention(self) -> bool:
        """Not healthy, but known: needs attention, or failed."""
        return self in (ScoreTone.NEEDS_ATTENTION, ScoreTone.FAILED)

    @property
    def is_failed(self) -> bool:
        """A Required standard failed: never just a low score."""
        return self is ScoreTone.FAILED
