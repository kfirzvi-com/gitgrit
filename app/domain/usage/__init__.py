"""Workspace usage: the two meters plans will be priced on.

Pure Python (no Django): the vocabulary every layer shares.

* ``BillingMonth`` — the calendar month (UTC) usage is counted over;
* ``DayUsage`` — one day's executions and the most projects that day;
* ``MonthUsage`` — a month of days: executions summed, projects at their peak,
  and the pace the month is on.

*Executions* are standard runs a workspace queued (webhooks, schedules,
manual runs): they proxy compute. *Projects* are the repositories and
artifact projects the workspace holds: the scope the buyer feels. Plans and
their limits are not decided yet, so nothing here knows about them.
"""
from app.domain.usage.billing_month import BillingMonth
from app.domain.usage.day_usage import DayUsage
from app.domain.usage.month_usage import MonthUsage
