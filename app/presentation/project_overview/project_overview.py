from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from app.application.delivery import DeliveryReport
from app.domain.delivery import RunningVersion
from app.models import Project, StandardExecution
from app.presentation.project_overview.activity_item import ActivityItem

# Recent activity listed on the Overview.
RECENT = 10


class ProjectOverview:
    """The project page's Overview's recent activity: what happened lately
    across the tabs — deployments, merges and standard results — newest
    first. Each item names the tab that shows more."""

    def __init__(self, project: Project, results: dict, delivery: DeliveryReport | None, now: datetime | None = None):
        self._project = project
        self._results = results
        self._delivery = delivery
        self._now = now or timezone.now()

    @property
    def activity(self) -> list[ActivityItem]:
        items = [*self._run_activity(), *self._delivery_activity()]
        return sorted(items, key=lambda item: item.at, reverse=True)[:RECENT]

    # --- Standards ---------------------------------------------------------------

    def _run_activity(self) -> list[ActivityItem]:
        tones = {"passed": "healthy", "failed": "failed", "error": "needs_attention"}
        return [
            ActivityItem("run", f"{run.standard_name} {run.get_status_display().lower()}", run.created_at, "results",
                         tone=tones.get(run.status, ""))
            for run in list(self._results.get("recent_executions") or [])[:RECENT]
            if run.status != StandardExecution.Status.RUNNING
        ]

    # --- Delivery ----------------------------------------------------------------

    def _delivery_activity(self) -> list[ActivityItem]:
        report = self._delivery
        if report is None:
            return []
        web = self._project.web_url
        items = []
        for deployment in report.recent[:RECENT]:
            label = RunningVersion.of(deployment.event).label
            items.append(ActivityItem(
                "deploy",
                f"Deployed {label}" if deployment.succeeded else f"Deploying {label} failed",
                deployment.deployed_at,
                "delivery",
                url=f"{web}/commit/{deployment.sha}" if web else "",
                tone="healthy" if deployment.succeeded else "failed",
            ))
        items += [
            ActivityItem("merge", f"Merged #{pr.number} {pr.title}", pr.merged_at, "delivery", url=pr.url)
            for pr in report.recently_merged
        ]
        return items
