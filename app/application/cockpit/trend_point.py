from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TrendPoint:
    """How many of the workspace's projects were healthy on a day, out of
    how many it had."""

    day: date
    healthy: int
    total: int
