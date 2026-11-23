from __future__ import annotations

from enum import StrEnum

from app.domain.schedules.invalid_schedule import InvalidSchedule


class RunTrigger(StrEnum):
    """What runs an attached standard on its project (rule 3). The
    declaration order is the display order."""

    CHANGES = "changes"
    SCHEDULE = "schedule"
    BOTH = "both"

    @property
    def label(self) -> str:
        return {
            RunTrigger.CHANGES: "On every change",
            RunTrigger.SCHEDULE: "On a schedule",
            RunTrigger.BOTH: "Changes and schedule",
        }[self]

    @property
    def description(self) -> str:
        return {
            RunTrigger.CHANGES: "Runs on each push and pull request its criteria match",
            RunTrigger.SCHEDULE: "Runs only at the scheduled times; its latest result counts in the score",
            RunTrigger.BOTH: "Runs on each matching change, and again at the scheduled times",
        }[self]

    @property
    def on_changes(self) -> bool:
        return self is not RunTrigger.SCHEDULE

    @property
    def on_schedule(self) -> bool:
        return self is not RunTrigger.CHANGES

    @classmethod
    def parse(cls, value) -> RunTrigger:
        """The trigger a posted value names, in any case; refuses one that
        names none."""
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            names = ", ".join(t.value for t in cls)
            raise InvalidSchedule(f"Unknown trigger {value!r}. Use one of: {names}.") from None

    @classmethod
    def of(cls, on_changes: bool, scheduled: bool) -> RunTrigger:
        if not scheduled:
            return cls.CHANGES
        return cls.BOTH if on_changes else cls.SCHEDULE
