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


def minutes_text(minutes: float) -> str:
    """Run time as people read it: seconds under a minute, one decimal
    under 100 minutes, whole minutes above."""
    if minutes <= 0:
        return "0 min"
    if minutes < 1:
        return f"{round(minutes * 60)}s"
    if minutes < 100:
        return f"{minutes:.1f} min"
    return f"{round(minutes):,} min"


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
    def minutes(self) -> str:
        return minutes_text(self.report.shown.minutes)

    @property
    def projected_minutes(self) -> str:
        return minutes_text(self.report.projected_minutes)

    @property
    def average_run(self) -> str:
        seconds = self.report.shown.average_run_seconds
        return f"{seconds:.0f}s" if seconds < 60 else f"{seconds / 60:.1f} min"

    @property
    def months(self):
        """(month usage, width %, is shown, minutes text) for each month, newest first."""
        return [
            (m, round(100 * m.executions / self.max_month), m.month == self.report.shown.month,
             minutes_text(m.minutes) if m.run_ms else "—")
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
                "minutes": minutes_text(d.minutes) if d.run_ms else "",
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
                "minutes": minutes_text(month.minutes) if month.run_ms else "",
                **self._split(month.breakdown),
            },
            "days": days,
        }

    @staticmethod
    def _split(breakdown: Breakdown) -> dict:
        projects = breakdown.by_project()

        def row(name, share):
            return [name, share.executions, minutes_text(share.minutes) if share.run_ms else ""]

        return {
            "by_trigger": [row(trigger_label(s.name), s) for s in breakdown.by_trigger()],
            "by_project": [row(s.name, s) for s in projects[:PROJECTS_SHOWN]],
            "more_projects": max(len(projects) - PROJECTS_SHOWN, 0),
        }
