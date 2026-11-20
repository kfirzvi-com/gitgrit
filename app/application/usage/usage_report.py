from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from app.domain.models import Project, WorkspaceUsageDay
from app.domain.usage import BillingMonth, MonthUsage

# How many months the report reaches back, the current one included.
MONTHS = 6


@dataclass(frozen=True)
class UsageReport:
    """A workspace's usage: the current month day by day, the months before
    it, and the projects it holds right now."""

    today: date
    current: MonthUsage
    history: tuple[MonthUsage, ...]  # newest first, current month excluded
    projects_now: int

    @classmethod
    def for_workspace(cls, tenant, *, today: date | None = None, months: int = MONTHS) -> UsageReport:
        today = today or timezone.now().date()
        window = [BillingMonth.of(today)]
        while len(window) < months:
            window.append(window[-1].previous())
        rows = WorkspaceUsageDay.objects.filter(
            tenant=tenant, day__gte=window[-1].first_day, day__lte=window[0].last_day
        )
        by_month: dict[BillingMonth, list] = {m: [] for m in window}
        for row in rows:
            by_month[BillingMonth.of(row.day)].append(row.usage)
        usages = [MonthUsage(m, tuple(by_month[m])) for m in window]
        return cls(
            today=today,
            current=usages[0],
            history=tuple(usages[1:]),
            projects_now=Project.objects.filter(tenant=tenant).count(),
        )

    @property
    def peak_projects(self) -> int:
        """This month's peak, which the projects held now are part of."""
        return max(self.current.peak_projects, self.projects_now)

    @property
    def projected_executions(self) -> int:
        return self.current.projected_executions(self.today)
