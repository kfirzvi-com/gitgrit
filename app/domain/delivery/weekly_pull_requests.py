from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class WeeklyPullRequests:
    """One week of pull request flow: how many merged during it, how long
    those had been open (the median, None without merges), and how many
    were still open when it ended."""

    starts: date
    merged: int
    open_at_end: int
    time_to_merge: timedelta | None = None
