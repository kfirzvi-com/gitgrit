from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from app.domain.models import ExecutionUsage, Project, WorkspaceUsageDay
from app.domain.usage import BillingMonth, DayUsage, MonthUsage

# How many months the report reaches back, the current one included.
MONTHS = 6


@dataclass(frozen=True)
class UsageReport:
    """A workspace's usage: one month day by day with its executions split
    by project and trigger (``shown``), the totals of the last ``MONTHS``
    months to pick from, and the projects it holds right now."""

    today: date
    shown: MonthUsage
    months: tuple[MonthUsage, ...]  # newest first, the current month included
    projects_now: int

    @classmethod
    def for_workspace(
        cls, tenant, *, month: BillingMonth | None = None, today: date | None = None, months: int = MONTHS
    ) -> UsageReport:
        """``month`` picks the month shown day by day: the current one by
        default, and only one of the months the report reaches."""
        today = today or timezone.now().date()
        window = [BillingMonth.of(today)]
        while len(window) < months:
            window.append(window[-1].previous())
        shown = month if month in window else window[0]

        rows = WorkspaceUsageDay.objects.filter(
            tenant=tenant, day__gte=window[-1].first_day, day__lte=window[0].last_day
        )
        slices: dict[date, list] = {}
        for usage in ExecutionUsage.objects.filter(
            tenant=tenant, day__gte=shown.first_day, day__lte=shown.last_day
        ):
            slices.setdefault(usage.day, []).append(usage.slice)

        by_month: dict[BillingMonth, list[DayUsage]] = {m: [] for m in window}
        for row in rows:
            by_month[BillingMonth.of(row.day)].append(
                DayUsage(row.day, row.executions, row.peak_projects, run_ms=row.run_ms, timed_runs=row.timed_runs,
                         slices=tuple(slices.get(row.day, ())))
            )
        usages = tuple(MonthUsage(m, tuple(by_month[m])) for m in window)
        return cls(
            today=today,
            shown=next(u for u in usages if u.month == shown),
            months=usages,
            projects_now=Project.objects.filter(tenant=tenant).count(),
        )

    @property
    def is_current(self) -> bool:
        return self.shown.month == BillingMonth.of(self.today)

    @property
    def peak_projects(self) -> int:
        """The shown month's peak; this month's includes the projects held now."""
        if self.is_current:
            return max(self.shown.peak_projects, self.projects_now)
        return self.shown.peak_projects

    @property
    def projected_executions(self) -> int:
        return self.shown.projected_executions(self.today)

    @property
    def projected_minutes(self) -> float:
        return self.shown.projected_minutes(self.today)

    @property
    def daily_average(self) -> float:
        return self.shown.daily_average(self.today)

    @property
    def newer(self) -> BillingMonth | None:
        months = [u.month for u in self.months]
        i = months.index(self.shown.month)
        return months[i - 1] if i > 0 else None

    @property
    def older(self) -> BillingMonth | None:
        months = [u.month for u in self.months]
        i = months.index(self.shown.month)
        return months[i + 1] if i + 1 < len(months) else None
