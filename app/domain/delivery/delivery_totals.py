from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Sequence

from app.domain.delivery.deployment_frequency import DeploymentFrequency
from app.domain.delivery.dora_tier import DoraTier
from app.domain.delivery.lead_time import LeadTime
from app.domain.delivery.pull_request_flow import PullRequestFlow


@dataclass(frozen=True)
class DeliveryTotals:
    """A workspace's delivery, week by week, summed over its projects (whose
    weeks all end on the same day): deployments, merges and pull requests
    open at each week's end, what is open now, how many projects sit in
    each deploy tier and each lead time tier, and the median lead time of
    every change shipped (each project measured from its own start), the
    typical project's deploys a week (the median project: DORA's bands are
    per project, so a workspace total has none) and how long the pull
    requests still open have been open."""

    starts: tuple[date, ...]
    deployments: tuple[int, ...]
    merged: tuple[int, ...]
    open_at_end: tuple[int, ...]
    open_now: int
    tiers: tuple[tuple[DoraTier, int], ...]
    lead_time: timedelta | None = None
    lead_tiers: tuple[tuple[DoraTier, int], ...] = ()
    typical_deploys_a_week: float = 0.0
    open_age: timedelta | None = None

    @classmethod
    def of(
        cls,
        frequencies: Sequence[DeploymentFrequency],
        flows: Sequence[PullRequestFlow],
        lead_times: Sequence[LeadTime] = (),
    ) -> DeliveryTotals:
        weeks = frequencies[0].weeks if frequencies else (flows[0].weeks if flows else ())
        count = len(weeks)

        def summed(rows, attribute):
            return tuple(sum(getattr(row.weeks[i], attribute) for row in rows) for i in range(count))

        tier_counts = {tier: 0 for tier in DoraTier}
        for frequency in frequencies:
            tier_counts[frequency.tier] += 1
        lead_counts = {tier: 0 for tier in DoraTier}
        for lead in lead_times:
            lead_counts[lead.tier] += 1
        lengths = [change.length for lead in lead_times for change in lead.changes]
        return cls(
            starts=tuple(week.starts for week in weeks),
            deployments=summed(frequencies, "deployments"),
            merged=summed(flows, "merged"),
            open_at_end=summed(flows, "open_at_end"),
            open_now=sum(flow.open_now for flow in flows),
            tiers=tuple(tier_counts.items()),
            lead_time=median(lengths) if lengths else None,
            lead_tiers=tuple(lead_counts.items()),
            typical_deploys_a_week=median([f.per_week for f in frequencies]) if frequencies else 0.0,
            open_age=median(ages) if (ages := [age for flow in flows for age in flow.open_ages]) else None,
        )

    @property
    def deployments_per_week(self) -> float:
        return sum(self.deployments) / len(self.deployments) if self.deployments else 0.0

    @property
    def merged_per_week(self) -> float:
        return sum(self.merged) / len(self.merged) if self.merged else 0.0
