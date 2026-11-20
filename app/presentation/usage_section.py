from __future__ import annotations

from app.domain.usage import Breakdown

# How the triggers runs carry (their event type) read on the page.
TRIGGER_LABELS = {
    "push": "Push",
    "pull_request": "Pull request",
    "merge_request": "Merge request",
    "manual": "Manual run",
    "upload": "Upload",
}
# How many projects a breakdown lists before "N more".
PROJECTS_SHOWN = 5


def trigger_label(trigger: str) -> str:
    return TRIGGER_LABELS.get(trigger, trigger.replace("_", " ").capitalize())


class UsageSection:
    """What workspace settings' Usage section draws from a ``UsageReport``:
    the shown month's days as bars scaled to its busiest day, the data its
    hover tooltips and day details read (``chart``), and the months to pick
    from as rows scaled to the busiest month."""

    def __init__(self, report):
        self.report = report
        self.days = report.shown.daily()
        self.max_day = max([d.executions for d in self.days] + [1])
        self.max_month = max([m.executions for m in report.months] + [1])

    @property
    def bars(self):
        """(index, day, height %, is future) for each day of the shown month."""
        return [
            (i, d, round(100 * d.executions / self.max_day), d.day > self.report.today)
            for i, d in enumerate(self.days)
        ]

    @property
    def average_percent(self) -> float:
        """Where the daily-average line sits, as % of the chart's height."""
        return round(100 * self.report.daily_average / self.max_day, 1)

    @property
    def months(self):
        """(month usage, width %, is shown) for each month, newest first."""
        return [
            (m, round(100 * m.executions / self.max_month), m.month == self.report.shown.month)
            for m in self.report.months
        ]

    @property
    def chart(self) -> dict:
        """The data the chart's script reads: each day with its breakdown,
        and the month as a whole for when no day is pinned."""
        average = self.report.daily_average
        running = self.report.shown.running_totals()
        days = []
        for d, total in zip(self.days, running):
            future = d.day > self.report.today
            days.append({
                "date": d.day.isoformat(),
                "label": f"{d.day:%a}, {d.day:%b} {d.day.day}",
                "executions": d.executions,
                "projects": d.projects,
                "running": total,
                "vs_average": None if future or not average else round(100 * (d.executions - average) / average),
                "future": future,
                "today": d.day == self.report.today,
                **self._split(d.breakdown),
            })
        month = self.report.shown
        return {
            "average": round(average, 1),
            "month": {
                "label": f"All of {month.month.label}",
                "executions": month.executions,
                "projects": self.report.peak_projects,
                **self._split(month.breakdown),
            },
            "days": days,
        }

    @staticmethod
    def _split(breakdown: Breakdown) -> dict:
        projects = breakdown.by_project()
        return {
            "by_trigger": [[trigger_label(t), n] for t, n in breakdown.by_trigger()],
            "by_project": [[name, n] for name, n in projects[:PROJECTS_SHOWN]],
            "more_projects": max(len(projects) - PROJECTS_SHOWN, 0),
        }
