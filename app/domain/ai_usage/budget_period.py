from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum


class BudgetPeriod(StrEnum):
    """The window a budget counts tokens over: the current calendar day, week
    (from Monday) or month, in the workspace's local time. A new window starts
    from zero."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"

    @property
    def label(self) -> str:
        return {BudgetPeriod.DAY: "Daily", BudgetPeriod.WEEK: "Weekly", BudgetPeriod.MONTH: "Monthly"}[self]

    @property
    def noun(self) -> str:
        return {BudgetPeriod.DAY: "today", BudgetPeriod.WEEK: "this week", BudgetPeriod.MONTH: "this month"}[self]

    def starts(self, now: datetime) -> datetime:
        """When the window ``now`` falls in began. ``now`` is local time."""
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if self is BudgetPeriod.DAY:
            return midnight
        if self is BudgetPeriod.WEEK:
            return midnight - timedelta(days=midnight.weekday())
        return midnight.replace(day=1)

    def ends(self, now: datetime) -> datetime:
        """When the window ``now`` falls in is over (the next one starts)."""
        start = self.starts(now)
        if self is BudgetPeriod.DAY:
            return start + timedelta(days=1)
        if self is BudgetPeriod.WEEK:
            return start + timedelta(weeks=1)
        return (start + timedelta(days=32)).replace(day=1)

    def last_day(self, now: datetime):
        """The last calendar day of the window ``now`` falls in."""
        return (self.ends(now) - timedelta(days=1)).date()

    def key(self, now: datetime) -> str:
        """A name for the window ``now`` falls in, unique per period kind."""
        return self.starts(now).date().isoformat()
