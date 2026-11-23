from __future__ import annotations


class InvalidSchedule(ValueError):
    """A schedule that cannot run: a cron expression that is not five valid
    fields, an unknown time zone, or "on a schedule" with no schedule."""
