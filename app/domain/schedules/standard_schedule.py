from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.schedules.cron_schedule import CronSchedule
from app.domain.schedules.invalid_schedule import InvalidSchedule
from app.domain.schedules.run_trigger import RunTrigger


@dataclass(frozen=True)
class StandardSchedule:
    """What runs one attached standard: its trigger and, when it runs on a
    schedule, the schedule (rule 3). A trigger on changes keeps no
    schedule."""

    trigger: RunTrigger = RunTrigger.CHANGES
    cron: CronSchedule | None = None

    def __post_init__(self):
        if self.trigger.on_schedule and self.cron is None:
            raise InvalidSchedule("Pick when it runs: a standard on a schedule needs a schedule.")
        if not self.trigger.on_schedule and self.cron is not None:
            object.__setattr__(self, "cron", None)

    @classmethod
    def parse(cls, trigger, cron_text: str = "", time_zone: str = "UTC") -> StandardSchedule:
        """From posted values. A trigger on changes ignores the schedule
        typed, so switching back to changes never fails on a half-typed
        one."""
        chosen = RunTrigger.parse(trigger or RunTrigger.CHANGES)
        if not chosen.on_schedule:
            return cls(chosen)
        return cls(chosen, CronSchedule.parse(cron_text, time_zone))

    @property
    def runs_on_changes(self) -> bool:
        return self.trigger.on_changes

    @property
    def expression(self) -> str:
        return self.cron.expression if self.cron else ""

    @property
    def time_zone(self) -> str:
        return self.cron.time_zone if self.cron else ""

    def next_run_after(self, moment: datetime) -> datetime | None:
        """When it is next due (rule 4); None when it runs on changes only."""
        return self.cron.next_run(moment) if self.cron else None
