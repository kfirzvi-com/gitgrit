"""Schedules: when an attached standard runs on a project besides (or instead
of) every change. Pure, no I/O, no ORM.

Rules:
1. A schedule is a standard five-field cron expression (minute, hour, day of
   month, month, day of week); the usual macros (``@daily``...) are spelled
   out into it. Anything else is refused, so a typo never becomes "never".
2. A schedule is read in a time zone (an IANA name, UTC by default): "every
   day at 09:00" in Asia/Jerusalem is 09:00 there, daylight saving included.
   The zone belongs to the schedule, not to whoever reads it: the team sees
   one schedule, "06:00 in Madrid", whatever their own zones.
3. An attached standard runs on every change, on its schedule, or both
   (``RunTrigger``). Running on a schedule needs a schedule.
4. A scheduled run runs on the project's default branch, at its newest
   commit, and is due at the schedule's next time after the last one it
   ran (or after the schedule was set). A worker down for a while runs a
   due standard once when it is back, not once per missed time.
5. A standard that runs only on its schedule never runs on a change: on the
   default branch its newest result stands in for it in every check, so the
   project score keeps every standard (``app.domain.scoring``).

Vocabulary, one class per term: ``CronSchedule``, ``CronDescription``,
``RunTrigger``, ``StandardSchedule``, ``InvalidSchedule``.
"""
from app.domain.schedules.cron_description import CronDescription
from app.domain.schedules.cron_schedule import CronSchedule
from app.domain.schedules.invalid_schedule import InvalidSchedule
from app.domain.schedules.run_trigger import RunTrigger
from app.domain.schedules.standard_schedule import StandardSchedule

__all__ = ["CronDescription", "CronSchedule", "InvalidSchedule", "RunTrigger", "StandardSchedule"]
