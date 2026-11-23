"""What the schedule editor shows under the cron box as it is typed: the
schedule in words and its next times in its time zone (and in the viewer's,
when that is another), or why it is not one."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain import schedules

# How many next times the editor lists.
NEXT_RUNS = 3
# More often than this, the editor says how many runs a day that is.
BUSY = timedelta(hours=1)


@dataclass(frozen=True)
class SchedulePreview:
    cron: str
    time_zone: str
    viewer_time_zone: str = ""

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
        viewer = self._viewer_zone(schedule.time_zone)
        return {
            "valid": True,
            "cron": schedule.expression,
            "text": schedules.CronDescription(schedule).text,
            "time_zone": schedule.time_zone,
            "next_runs": [_when(r) for r in runs],
            "viewer_time_zone": viewer.key if viewer else "",
            "viewer_next_runs": [_when(r.astimezone(viewer)) for r in runs] if viewer else [],
            "warning": warning,
        }

    def _viewer_zone(self, schedule_zone: str) -> ZoneInfo | None:
        """The viewer's zone when it is a real one other than the
        schedule's; else none (their times are the schedule's)."""
        if not self.viewer_time_zone or self.viewer_time_zone == schedule_zone:
            return None
        try:
            return ZoneInfo(self.viewer_time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            return None


def _when(moment: datetime) -> str:
    return moment.strftime("%a %-d %b, %H:%M")
