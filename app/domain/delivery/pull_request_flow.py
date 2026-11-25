from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from statistics import median
from typing import Iterable

from app.domain.delivery.deployment_frequency import WEEKS
from app.domain.delivery.pull_request_facts import PullRequestFacts
from app.domain.delivery.pull_request_state import PullRequestState
from app.domain.delivery.weekly_pull_requests import WeeklyPullRequests


@dataclass(frozen=True)
class PullRequestFlow:
    """How pull requests move through a project over the last ``WEEKS``
    weeks, ending on ``ends`` (the same weeks as deployment frequency):
    merges per week, how many were open at each week's end, what is open
    now, and how long pull requests stay open — merged ones from opening to
    merge (the time to merge), open ones so far (their age). A pull request
    closed unmerged leaves the open count but is no merge."""

    ends: date
    weeks: tuple[WeeklyPullRequests, ...]
    open_now: int
    oldest_open_since: datetime | None
    time_to_merge: timedelta | None = None
    open_ages: tuple[timedelta, ...] = ()

    @classmethod
    def of(
        cls,
        pull_requests: Iterable[PullRequestFacts],
        ends: date,
        tz: tzinfo = timezone.utc,
        now: datetime | None = None,
    ) -> PullRequestFlow:
        """``now`` ages the open pull requests; by default, the end of ``ends``."""
        prs = list(pull_requests)
        now = now or datetime.combine(ends, time.max, tzinfo=tz)
        starts = ends - timedelta(weeks=WEEKS) + timedelta(days=1)

        def day(moment: datetime | None) -> date | None:
            return moment.astimezone(tz).date() if moment else None

        weeks = []
        for index in range(WEEKS):
            first = starts + timedelta(weeks=index)
            last = min(first + timedelta(days=6), ends)
            merged_in_week = [pr for pr in prs if pr.merged_at and first <= day(pr.merged_at) <= last]
            merged = len(merged_in_week)
            still_open = sum(
                1
                for pr in prs
                if day(pr.created_at) <= last and (pr.closed_at is None or day(pr.closed_at) > last)
            )
            weeks.append(
                WeeklyPullRequests(
                    starts=first, merged=merged, open_at_end=still_open, time_to_merge=_time_to_merge(merged_in_week)
                )
            )
        open_prs = [pr for pr in prs if pr.state is PullRequestState.OPEN]
        merged_in_window = [pr for pr in prs if pr.merged_at and day(pr.merged_at) >= starts]
        return cls(
            ends=ends,
            weeks=tuple(weeks),
            open_now=len(open_prs),
            oldest_open_since=min((pr.created_at for pr in open_prs), default=None),
            time_to_merge=_time_to_merge(merged_in_window),
            open_ages=tuple(now - pr.created_at for pr in open_prs),
        )

    @property
    def starts(self) -> date:
        return self.weeks[0].starts

    @property
    def open_age(self) -> timedelta | None:
        """How long the pull requests still open have been open (median)."""
        return median(self.open_ages) if self.open_ages else None

    @property
    def merged(self) -> int:
        return sum(week.merged for week in self.weeks)

    @property
    def merged_per_week(self) -> float:
        return self.merged / len(self.weeks)


def _time_to_merge(merged: list[PullRequestFacts]) -> timedelta | None:
    """The median time from opening to merge."""
    return median([pr.merged_at - pr.created_at for pr in merged]) if merged else None
