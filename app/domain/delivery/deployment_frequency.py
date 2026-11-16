from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta, timezone, tzinfo
from statistics import median
from typing import Iterable

from app.domain.delivery.deployment_event import DeploymentEvent
from app.domain.delivery.dora_tier import DoraTier
from app.domain.delivery.weekly_deployments import WeeklyDeployments

WEEKS = 13
_MONTH_DAYS = 28


@dataclass(frozen=True)
class DeploymentFrequency:
    """How often a project ships to production over the last ``WEEKS`` weeks
    (about a quarter), ending on ``ends``.

    Counted in changes shipped, not in deploy jobs: only successful
    deployments count, and a commit that reaches production twice (a
    redeploy, a second production region) counts once, on its first arrival.

    The tier follows the Four Keys reading of DORA, which looks at the
    typical week or month rather than the average, so one busy release week
    does not lift a quiet quarter:

    * Elite — in the median week, deploys land on 3 or more days;
    * High — the median week has a deploy;
    * Medium — the median 4-week stretch has a deploy, and there are as many
      deploys as stretches (with only three stretches, the median alone
      would rank a deploy every two months as monthly);
    * Low — there are deploys, but less often than that.
    """

    ends: date
    weeks: tuple[WeeklyDeployments, ...]

    @classmethod
    def of(
        cls,
        deployments: Iterable[DeploymentEvent],
        ends: date,
        tz: tzinfo = timezone.utc,
    ) -> DeploymentFrequency:
        starts = ends - timedelta(weeks=WEEKS) + timedelta(days=1)
        shipped_on: dict[str, date] = {}
        for deployment in sorted(deployments, key=lambda d: d.deployed_at):
            if not deployment.succeeded or deployment.sha in shipped_on:
                continue
            shipped_on[deployment.sha] = deployment.deployed_at.astimezone(tz).date()
        per_day = Counter(day for day in shipped_on.values() if starts <= day <= ends)
        weeks = []
        for index in range(WEEKS):
            first = starts + timedelta(weeks=index)
            days = [first + timedelta(days=offset) for offset in range(7)]
            weeks.append(
                WeeklyDeployments(
                    starts=first,
                    deployments=sum(per_day[day] for day in days),
                    deploy_days=sum(1 for day in days if per_day[day]),
                )
            )
        return cls(ends=ends, weeks=tuple(weeks))

    @property
    def starts(self) -> date:
        return self.weeks[0].starts

    @property
    def total(self) -> int:
        return sum(week.deployments for week in self.weeks)

    @property
    def per_week(self) -> float:
        return self.total / len(self.weeks)

    @property
    def tier(self) -> DoraTier:
        if not self.total:
            return DoraTier.NONE
        if median(week.deploy_days for week in self.weeks) >= 3:
            return DoraTier.ELITE
        if median(week.deployments for week in self.weeks) >= 1:
            return DoraTier.HIGH
        stretches = self._four_week_totals()
        if median(stretches) >= 1 and sum(stretches) >= len(stretches):
            return DoraTier.MEDIUM
        return DoraTier.LOW

    def _four_week_totals(self) -> list[int]:
        """Deploys per 4-week stretch, counted back from the newest week (the
        oldest week left over joins no stretch)."""
        newest_first = list(reversed(self.weeks))
        stretch = _MONTH_DAYS // 7
        return [
            sum(week.deployments for week in newest_first[index : index + stretch])
            for index in range(0, len(newest_first) - stretch + 1, stretch)
        ]
