from __future__ import annotations

from app.domain.usage import Breakdown
from app.presentation.usage_metric import UsageMetric

# How the triggers runs carry (their event type) read on the page.
TRIGGER_LABELS = {
    "push": "Push",
    "pull_request": "Pull request",
    "merge_request": "Merge request",
    "manual": "Manual run",
    "upload": "Upload",
    "schedule": "Scheduled run",
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
        self.max_month_ms = max([m.run_ms for m in report.months] + [1])

    @property
    def bars(self):
        """(index, day, height %, is future) for each day of the shown month."""
        return [
            (i, d, round(100 * d.executions / self.max_day), d.day > self.report.today)
            for i, d in enumerate(self.days)
        ]

    @property
    def average_percent(self) -> float:
        """Where the executions' daily-average line sits, as % of the chart's
        height (the chart opens on executions)."""
        return round(100 * self.report.daily_average / self.max_day, 1)

    # The details panel's two lists: (heading, data key the script fills).
    detail_lists = (("By trigger", "triggers"), ("By project", "projects"))

    @property
    def metrics(self) -> list[UsageMetric]:
        """The executions card and the run-time card, in the chart's order."""
        r, month = self.report, self.report.shown
        pace = "Pace by month end" if r.is_current else "Whole month"
        busiest = month.busiest_day("executions")
        executions = UsageMetric(
            key="executions", label="Executions", unit="executions",
            total=f"{month.executions:,}",
            figures=(
                (pace, f"{r.projected_executions:,}"),
                ("Per day (avg)", f"{round(r.daily_average):,}"),
                ("Busiest day", f"{busiest.executions:,} on {busiest.day:%b} {busiest.day.day}" if busiest else "—"),
            ),
        )
        slowest = month.busiest_day("run_ms")
        seconds = month.average_run_seconds
        run_time = UsageMetric(
            key="run_time", label="Run time", unit="minutes",
            total=minutes_text(month.minutes),
            figures=(
                (pace, minutes_text(r.projected_minutes)),
                ("Per day (avg)", minutes_text(month.daily_average_minutes(r.today))),
                ("Per run (avg)", (f"{seconds:.0f}s" if seconds < 60 else f"{seconds / 60:.1f} min") if seconds else "—"),
                ("Busiest day", f"{minutes_text(slowest.minutes)} on {slowest.day:%b} {slowest.day.day}" if slowest else "—"),
            ),
            note="" if month.run_ms else "Measured from when run time tracking began.",
        )
        return [executions, run_time]

    @property
    def months(self):
        """(month usage, executions width %, is shown, run-time text, run-time
        width %) for each month, newest first."""
        return [
            (m, round(100 * m.executions / self.max_month), m.month == self.report.shown.month,
             minutes_text(m.minutes) if m.run_ms else "—", round(100 * m.run_ms / self.max_month_ms))
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
                "run_ms": d.run_ms,
                "minutes": minutes_text(d.minutes) if d.run_ms else "",
                "running": total,
                "future": future,
                "today": d.day == self.report.today,
                **self._split(d.breakdown),
            })
        month = self.report.shown
        return {
            "average": {"executions": average, "run_ms": month.daily_average_minutes(self.report.today) * 60_000},
            "month": {
                "label": f"All of {month.month.label}",
                "executions": month.executions,
                "run_ms": month.run_ms,
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
            return [name, share.executions, share.run_ms, minutes_text(share.minutes) if share.run_ms else ""]

        return {
            "by_trigger": [row(trigger_label(s.name), s) for s in breakdown.by_trigger()],
            "by_project": [row(s.name, s) for s in projects[:PROJECTS_SHOWN]],
            "more_projects": max(len(projects) - PROJECTS_SHOWN, 0),
        }
