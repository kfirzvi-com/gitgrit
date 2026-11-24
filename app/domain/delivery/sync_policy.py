from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class SyncPolicy:
    """How often a project's delivery data is read from its Git platform.

    Pages never read the platform: they show what the last sync stored. A
    sync runs every ``interval`` on a schedule (webhooks bring most changes
    in sooner), and asking for one by hand is allowed once per ``cooldown``,
    so a busy Refresh button cannot spend the platform's rate limit.
    """

    interval: timedelta = timedelta(minutes=15)
    cooldown: timedelta = timedelta(minutes=5)

    def __post_init__(self):
        if self.interval <= timedelta(0) or self.cooldown < timedelta(0):
            raise ValueError("A sync interval must be positive and a cooldown not negative.")

    def is_due(self, synced_at: datetime | None, now: datetime) -> bool:
        """The scheduled sync should run: never synced, or synced at least
        ``interval`` ago."""
        return synced_at is None or now - synced_at >= self.interval

    def may_refresh(self, synced_at: datetime | None, now: datetime) -> bool:
        """A sync asked for by hand may run now."""
        return synced_at is None or now - synced_at >= self.cooldown

    def next_refresh(self, synced_at: datetime) -> datetime:
        """When asking by hand is allowed again."""
        return synced_at + self.cooldown
