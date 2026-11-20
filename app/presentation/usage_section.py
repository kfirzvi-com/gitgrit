from __future__ import annotations


class UsageSection:
    """What workspace settings' Usage section draws from a ``UsageReport``:
    this month's days as bars scaled to its busiest day, and the months
    before it as rows scaled to the busiest month."""

    def __init__(self, report):
        self.report = report
        self.days = report.current.daily()
        self.max_day = max([d.executions for d in self.days] + [1])
        self.max_month = max([m.executions for m in report.history] + [report.current.executions, 1])

    @property
    def bars(self):
        """(day, height %, is future) for each day of this month."""
        return [
            (d, round(100 * d.executions / self.max_day), d.day > self.report.today)
            for d in self.days
        ]

    @property
    def months(self):
        """(month usage, width %) for the months before this one, newest first."""
        return [(m, round(100 * m.executions / self.max_month)) for m in self.report.history]
