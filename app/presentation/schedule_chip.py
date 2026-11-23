"""How a standards table row says what runs the standard: its chip."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain import schedules


@dataclass(frozen=True)
class ScheduleChip:
    """The row's trigger, schedule and the words its chip shows
    ("On every change", "Every day at 09:00", "Changes + every day at
    09:00")."""

    trigger: str
    schedule: str
    time_zone: str
    label: str

    @classmethod
    def of(cls, standard_schedule: schedules.StandardSchedule, default_time_zone: str) -> ScheduleChip:
        trigger = standard_schedule.trigger
        if not standard_schedule.cron:
            return cls(trigger.value, "", default_time_zone, trigger.label)
        text = schedules.CronDescription(standard_schedule.cron).text
        if trigger is schedules.RunTrigger.BOTH:
            text = "Changes + " + text[0].lower() + text[1:]
        return cls(trigger.value, standard_schedule.expression, standard_schedule.time_zone, text)

    @staticmethod
    def trigger_options() -> list[dict]:
        return [{"value": t.value, "label": t.label, "description": t.description} for t in schedules.RunTrigger]
