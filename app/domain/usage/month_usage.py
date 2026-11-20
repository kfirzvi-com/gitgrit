from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.domain.usage.billing_month import BillingMonth
from app.domain.usage.breakdown import Breakdown
from app.domain.usage.day_usage import DayUsage


@dataclass(frozen=True)
class MonthUsage:
    """A month of a workspace's usage, one ``DayUsage`` per recorded day.

    Executions add up over the month; projects count at their peak, the way
    a plan's project limit would read them (adding and removing a project
    the same month still used a slot)."""

    month: BillingMonth
    days: tuple[DayUsage, ...] = field(default_factory=tuple)

    def __post_init__(self):
        strays = [d.day for d in self.days if BillingMonth.of(d.day) != self.month]
        if strays:
            raise ValueError(f"{strays[0]} is not in {self.month}")

    @property
    def executions(self) -> int:
        return sum(d.executions for d in self.days)

    @property
    def peak_projects(self) -> int:
        return max((d.projects for d in self.days), default=0)

    @property
    def breakdown(self) -> Breakdown:
        return Breakdown(s for d in self.days for s in d.slices)

    def daily_average(self, today: date) -> float:
        """Executions per day over the days the month has had so far."""
        if today < self.month.first_day:
            return 0.0
        elapsed = self.month.length if today >= self.month.last_day else today.day
        return self.executions / elapsed

    def running_totals(self) -> list[int]:
        """Executions from the 1st through each day of the month."""
        totals, total = [], 0
        for d in self.daily():
            total += d.executions
            totals.append(total)
        return totals

    def daily(self) -> list[DayUsage]:
        """Every day of the month in order, empty days included."""
        recorded = {d.day: d for d in self.days}
        return [recorded.get(day, DayUsage(day)) for day in self.month.days()]

    def projected_executions(self, today: date) -> int:
        """Where executions end the month at the pace so far. A past month
        projects what it counted; a month not started projects nothing."""
        if today >= self.month.last_day:
            return self.executions
        if today < self.month.first_day:
            return 0
        elapsed = today.day  # today counts: its runs are already in
        return round(self.executions * self.month.length / elapsed)
