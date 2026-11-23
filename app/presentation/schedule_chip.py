"""How a standards table row says what runs the standard: its chip."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain import schedules
from app.presentation.time_zone_label import TimeZoneLabel


@dataclass(frozen=True)
class ScheduleChip:
    """The row's trigger, schedule and time zone, and the words its chip
    shows ("On every change", "Every day at 09:00", "Changes + every day at
    09:00"), with the schedule's zone ("Madrid") beside them: the times are
    the schedule's, the same for every reader. A row with no schedule has
    ``default_time_zone`` (empty: the editor starts from the browser's)."""

    trigger: str
    schedule: str
    time_zone: str
    label: str
    zone_label: str = ""

    @classmethod
    def of(cls, standard_schedule: schedules.StandardSchedule, default_time_zone: str = "") -> ScheduleChip:
        trigger = standard_schedule.trigger
        if not standard_schedule.cron:
            return cls(trigger.value, "", default_time_zone, trigger.label)
        text = schedules.CronDescription(standard_schedule.cron).text
        if trigger is schedules.RunTrigger.BOTH:
            text = "Changes + " + text[0].lower() + text[1:]
        zone = standard_schedule.time_zone
        return cls(trigger.value, standard_schedule.expression, zone, text, TimeZoneLabel(zone).text)

    @staticmethod
    def trigger_options() -> list[dict]:
        return [{"value": t.value, "label": t.label, "description": t.description} for t in schedules.RunTrigger]
