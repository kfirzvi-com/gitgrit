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
    def run_ms(self) -> int:
        return sum(d.run_ms for d in self.days)

    @property
    def minutes(self) -> float:
        return self.run_ms / 60_000

    @property
    def average_run_seconds(self) -> float:
        """How long the month's timed runs took on average. Only runs whose
        time was measured count: runs from before timing began (even earlier
        the same day) would otherwise pull it down."""
        timed = sum(d.timed_runs for d in self.days)
        return self.run_ms / 1000 / timed if timed else 0.0

    @property
    def peak_projects(self) -> int:
        return max((d.projects for d in self.days), default=0)

    @property
    def breakdown(self) -> Breakdown:
        return Breakdown(s for d in self.days for s in d.slices)

    def daily_average(self, today: date) -> float:
        """Executions per day over the days the month has had so far."""
        return self._per_day(self.executions, today)

    def daily_average_minutes(self, today: date) -> float:
        """Run minutes per day over the days the month has had so far."""
        return self._per_day(self.minutes, today)

    def busiest_day(self, metric: str = "executions") -> DayUsage | None:
        """The day with the most ``executions`` or ``run_ms``; None when the
        month has none."""
        top = max(self.days, key=lambda d: (getattr(d, metric), -d.day.toordinal()), default=None)
        return top if top and getattr(top, metric) else None

    def _per_day(self, total: float, today: date) -> float:
        if today < self.month.first_day:
            return 0.0
        elapsed = self.month.length if today >= self.month.last_day else today.day
        return total / elapsed

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
        return round(self._projected(self.executions, today))

    def projected_minutes(self, today: date) -> float:
        """Where run minutes end the month at the pace so far."""
        return self._projected(self.minutes, today)

    def _projected(self, so_far: float, today: date) -> float:
        if today >= self.month.last_day:
            return so_far
        if today < self.month.first_day:
            return 0
        elapsed = today.day  # today counts: its runs are already in
        return so_far * self.month.length / elapsed
