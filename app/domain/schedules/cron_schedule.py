from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from app.domain.schedules.invalid_schedule import InvalidSchedule

# The macros developers know, spelled out (rule 1).
MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}
FIELD_NAMES = ("minute", "hour", "day of month", "month", "day of week")
MAX_LENGTH = 100


@dataclass(frozen=True)
class CronSchedule:
    """A five-field cron expression read in a time zone (rules 1 and 2).
    Only a valid one is made, however it is built."""

    expression: str
    time_zone: str = "UTC"

    def __post_init__(self):
        fields = self.expression.split()
        if len(fields) != len(FIELD_NAMES):
            raise InvalidSchedule(
                f"A schedule has {len(FIELD_NAMES)} fields (minute hour day-of-month month day-of-week), "
                f"not {len(fields)}."
            )
        if len(self.expression) > MAX_LENGTH or not croniter.is_valid(self.expression):
            raise InvalidSchedule(f"{self.expression!r} is not a valid cron schedule.")
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise InvalidSchedule(f"Unknown time zone: {self.time_zone!r}") from None

    @classmethod
    def parse(cls, text: str, time_zone: str = "UTC") -> CronSchedule:
        """A schedule from what a person typed: spaces normalised, a macro
        spelled out."""
        normal = " ".join(str(text or "").split())
        normal = MACROS.get(normal.lower(), normal)
        if not normal:
            raise InvalidSchedule("Enter a schedule.")
        return cls(normal, time_zone or "UTC")

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(self.expression.split())

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.time_zone)

    def next_runs(self, after: datetime, count: int = 1) -> list[datetime]:
        """The schedule's next ``count`` times strictly after ``after``, in
        its time zone."""
        it = croniter(self.expression, after.astimezone(self.zone))
        return [it.get_next(datetime) for _ in range(count)]

    def next_run(self, after: datetime) -> datetime:
        return self.next_runs(after, 1)[0]

    def shortest_gap(self, after: datetime, samples: int = 24) -> timedelta:
        """The shortest time between two of its next ``samples`` runs: how
        often it runs at its busiest."""
        times = self.next_runs(after, samples)
        return min(b - a for a, b in zip(times, times[1:]))
