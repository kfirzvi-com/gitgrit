from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DayUsage:
    """One UTC day of a workspace's usage: the standard runs it queued and
    the most projects it held at once."""

    day: date
    executions: int = 0
    projects: int = 0
