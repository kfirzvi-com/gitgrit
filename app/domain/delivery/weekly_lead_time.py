from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class WeeklyLeadTime:
    """One week of lead time: how many changes reached production in it,
    and their median lead time (None without any)."""

    starts: date
    changes: int
    median: timedelta | None = None
