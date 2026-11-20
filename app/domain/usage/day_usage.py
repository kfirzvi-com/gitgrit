from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.domain.usage.breakdown import Breakdown
from app.domain.usage.execution_slice import ExecutionSlice


@dataclass(frozen=True)
class DayUsage:
    """One UTC day of a workspace's usage: the standard runs it queued and
    the most projects it held at once, with the executions split by
    project and trigger when they were read."""

    day: date
    executions: int = 0
    projects: int = 0
    slices: tuple[ExecutionSlice, ...] = field(default_factory=tuple)

    @property
    def breakdown(self) -> Breakdown:
        return Breakdown(self.slices)
