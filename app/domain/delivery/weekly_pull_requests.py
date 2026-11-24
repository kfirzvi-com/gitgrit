from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WeeklyPullRequests:
    """One week of pull request flow: how many merged during it, and how
    many were still open when it ended."""

    starts: date
    merged: int
    open_at_end: int
