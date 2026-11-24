from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Iterable

from app.domain.delivery.deployment_frequency import WEEKS
from app.domain.delivery.pull_request_facts import PullRequestFacts
from app.domain.delivery.pull_request_state import PullRequestState
from app.domain.delivery.weekly_pull_requests import WeeklyPullRequests


@dataclass(frozen=True)
class PullRequestFlow:
    """How pull requests move through a project over the last ``WEEKS``
    weeks, ending on ``ends`` (the same weeks as deployment frequency):
    merges per week, how many were open at each week's end, and what is
    open now. A pull request closed unmerged leaves the open count but is
    no merge."""

    ends: date
    weeks: tuple[WeeklyPullRequests, ...]
    open_now: int
    oldest_open_since: datetime | None

    @classmethod
    def of(
        cls,
        pull_requests: Iterable[PullRequestFacts],
        ends: date,
        tz: tzinfo = timezone.utc,
    ) -> PullRequestFlow:
        prs = list(pull_requests)
        starts = ends - timedelta(weeks=WEEKS) + timedelta(days=1)

        def day(moment: datetime | None) -> date | None:
            return moment.astimezone(tz).date() if moment else None

        weeks = []
        for index in range(WEEKS):
            first = starts + timedelta(weeks=index)
            last = min(first + timedelta(days=6), ends)
            merged = sum(1 for pr in prs if pr.merged_at and first <= day(pr.merged_at) <= last)
            still_open = sum(
                1
                for pr in prs
                if day(pr.created_at) <= last and (pr.closed_at is None or day(pr.closed_at) > last)
            )
            weeks.append(WeeklyPullRequests(starts=first, merged=merged, open_at_end=still_open))
        open_prs = [pr for pr in prs if pr.state is PullRequestState.OPEN]
        return cls(
            ends=ends,
            weeks=tuple(weeks),
            open_now=len(open_prs),
            oldest_open_since=min((pr.created_at for pr in open_prs), default=None),
        )

    @property
    def starts(self) -> date:
        return self.weeks[0].starts

    @property
    def merged(self) -> int:
        return sum(week.merged for week in self.weeks)

    @property
    def merged_per_week(self) -> float:
        return self.merged / len(self.weeks)
