from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta, timezone, tzinfo
from statistics import median
from typing import Iterable

from app.domain.delivery.change_lead_time import ChangeLeadTime
from app.domain.delivery.deployment_frequency import WEEKS
from app.domain.delivery.dora_tier import DoraTier
from app.domain.delivery.lead_time_start import LeadTimeStart
from app.domain.delivery.pull_request_facts import PullRequestFacts
from app.domain.delivery.shipment import Shipment
from app.domain.delivery.weekly_lead_time import WeeklyLeadTime

# DORA's lead time bands: the median change reaches production within a day
# (elite), a week (high), a month (medium), or later (low).
_BANDS = ((timedelta(days=1), DoraTier.ELITE), (timedelta(weeks=1), DoraTier.HIGH), (timedelta(days=30), DoraTier.MEDIUM))


@dataclass(frozen=True)
class LeadTime:
    """DORA lead time for changes over the last ``WEEKS`` weeks, ending on
    ``ends``: how long changes took to reach production, from ``start``.

    A change is a commit (starting at ``COMMIT``) or, starting at ``READY``
    or ``MERGE``, a pull request, found by its merge commit among what a
    deployment shipped; commits pushed with no pull request count from when
    they were written. With a pull request start, only the deployed
    branch's own line of commits counts, so a merged pull request's inner
    commits are not counted twice. For pull requests, the median time in
    review (ready to merged) and waiting to deploy (merged to production)
    show where the time goes."""

    start: LeadTimeStart
    ends: date
    weeks: tuple[WeeklyLeadTime, ...]
    changes: tuple[ChangeLeadTime, ...]

    @classmethod
    def of(
        cls,
        shipments: Iterable[Shipment],
        pull_requests: Iterable[PullRequestFacts],
        ends: date,
        start: LeadTimeStart = LeadTimeStart.COMMIT,
        tz: tzinfo = timezone.utc,
    ) -> LeadTime:
        by_merge = {pr.merge_commit_sha: pr for pr in pull_requests if pr.merge_commit_sha and pr.merged_at}
        first_day = ends - timedelta(weeks=WEEKS) + timedelta(days=1)
        changes, seen = [], set()
        for shipment in sorted(shipments, key=lambda s: s.deployed_at):
            # A commit counts at its first arrival (shipped again after a
            # rollback, it is not a new change).
            fresh = Shipment(shipment.head_sha, shipment.deployed_at, tuple(c for c in shipment.commits if c.sha not in seen))
            seen.update(c.sha for c in shipment.commits)
            if first_day <= shipment.deployed_at.astimezone(tz).date() <= ends:
                changes.extend(cls._changes(fresh, by_merge, start))
        weeks = []
        for index in range(WEEKS):
            first = first_day + timedelta(weeks=index)
            last = first + timedelta(days=6)
            in_week = [c.length for c in changes if first <= c.deployed_at.astimezone(tz).date() <= last]
            weeks.append(WeeklyLeadTime(starts=first, changes=len(in_week), median=median(in_week) if in_week else None))
        return cls(start=start, ends=ends, weeks=tuple(weeks), changes=tuple(changes))

    @staticmethod
    def _changes(shipment: Shipment, by_merge: dict, start: LeadTimeStart) -> list[ChangeLeadTime]:
        commits = shipment.commits if start is LeadTimeStart.COMMIT else tuple(shipment.mainline())
        changes = []
        for commit in commits:
            pr = by_merge.get(commit.sha)
            ready = (pr.ready_at or pr.created_at) if pr else None
            if pr is None or start is LeadTimeStart.COMMIT:
                started = commit.authored_at
            elif start is LeadTimeStart.READY:
                started = ready
            else:
                started = pr.merged_at
            changes.append(
                ChangeLeadTime(
                    started_at=started,
                    deployed_at=shipment.deployed_at,
                    pull_request=pr.number if pr else None,
                    ready_at=ready,
                    merged_at=pr.merged_at if pr else None,
                )
            )
        return changes

    @property
    def starts(self) -> date:
        return self.weeks[0].starts

    @property
    def median(self) -> timedelta | None:
        return median([c.length for c in self.changes]) if self.changes else None

    @property
    def tier(self) -> DoraTier:
        if self.median is None:
            return DoraTier.NONE
        for limit, tier in _BANDS:
            if self.median < limit:
                return tier
        return DoraTier.LOW

    @property
    def review(self) -> timedelta | None:
        """The median time pull requests spent from ready to merged."""
        times = [c.review for c in self.changes if c.review is not None]
        return median(times) if times else None

    @property
    def waiting(self) -> timedelta | None:
        """The median time merged pull requests waited for production."""
        times = [c.waiting for c in self.changes if c.waiting is not None]
        return median(times) if times else None

    @property
    def through_pull_requests(self) -> int:
        return sum(1 for c in self.changes if c.pull_request is not None)
