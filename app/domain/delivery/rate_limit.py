from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# The share of the hourly allowance kept back: below it, delivery syncs stop
# until the allowance resets, leaving the rest for standard runs and pages.
RESERVE = 0.1


@dataclass(frozen=True)
class RateLimit:
    """What a platform said is left of a token's API allowance."""

    limit: int
    remaining: int
    resets_at: datetime

    def is_low(self, now: datetime) -> bool:
        """Little enough is left that syncing should wait for the reset."""
        return now < self.resets_at and self.remaining < self.limit * RESERVE
