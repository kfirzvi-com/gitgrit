"""What the schedule editor shows under the cron box as it is typed: the
schedule in words and its next times, or why it is not one."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain import schedules

# How many next times the editor lists.
NEXT_RUNS = 3
# More often than this, the editor says how many runs a day that is.
BUSY = timedelta(hours=1)


@dataclass(frozen=True)
class SchedulePreview:
    cron: str
    time_zone: str

    def as_dict(self, now: datetime) -> dict:
        try:
            schedule = schedules.CronSchedule.parse(self.cron, self.time_zone)
        except schedules.InvalidSchedule as exc:
            return {"valid": False, "error": str(exc)}
        runs = schedule.next_runs(now, NEXT_RUNS)
        gap = schedule.shortest_gap(now)
        warning = ""
        if gap < BUSY:
            per_day = round(timedelta(days=1) / gap)
            warning = (
                f"Runs up to {per_day} times a day. Every run is a sandbox run, "
                "and a standard that calls an LLM pays for each one."
            )
        return {
            "valid": True,
            "cron": schedule.expression,
            "text": schedules.CronDescription(schedule).text,
            "time_zone": schedule.time_zone,
            "next_runs": [r.strftime("%a %-d %b, %H:%M") for r in runs],
            "warning": warning,
        }
