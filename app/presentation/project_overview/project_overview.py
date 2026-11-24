from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from app.application.delivery import DeliveryReport
from app.domain.delivery import DoraTier, RunningVersion
from app.models import Project, StandardExecution
from app.presentation.project_overview.activity_item import ActivityItem
from app.presentation.project_overview.attention_item import AttentionItem

# Past this, a commit waiting to ship or a pull request still open wants a look.
STALE = timedelta(days=7)
# Recent activity listed on the Overview.
RECENT = 8
# Failing standards named one by one; past this, counted.
NAMED = 3


class ProjectOverview:
    """The project page's Overview: what wants a look across every tab, worst
    first, and what happened lately (deployments, merges, standard results),
    newest first. Each item names the tab that shows more."""

    def __init__(self, project: Project, results: dict, delivery: DeliveryReport | None, now: datetime | None = None):
        self._project = project
        self._results = results
        self._delivery = delivery
        self._now = now or timezone.now()

    @property
    def attention(self) -> list[AttentionItem]:
        return [*self._standards_attention(), *self._delivery_attention()]

    @property
    def activity(self) -> list[ActivityItem]:
        items = [*self._run_activity(), *self._delivery_activity()]
        return sorted(items, key=lambda item: item.at, reverse=True)[:RECENT]

    # --- Standards ---------------------------------------------------------------

    def _standards_attention(self) -> list[AttentionItem]:
        if not self._results.get("attached_standards") and not self._project.is_artifact:
            return [AttentionItem("No standards attached", "standards", detail="Nothing checks this project yet.")]
        items = []
        if not self._results.get("project_has_score"):
            branch = self._project.default_branch or "the default branch"
            items.append(AttentionItem(f"No score on {branch} yet", "results", detail="Its newest commit needs a result from every standard."))
        latest = self._results.get("latest_executions") or []
        failed = StandardExecution.Status.FAILED
        required = [r.standard_name for r in latest if r.status == failed and r.importance == "required"]
        others = [r.standard_name for r in latest if r.status == failed and r.importance != "required"]
        errored = [r.standard_name for r in latest if r.status == StandardExecution.Status.ERROR]
        if required:
            items.append(AttentionItem(_counted(len(required), "Required standard") + " failed", "results", "failed", _named(required)))
        if others:
            items.append(AttentionItem(_counted(len(others), "standard") + " failed", "results", detail=_named(others)))
        if errored:
            items.append(AttentionItem(_counted(len(errored), "standard") + " could not run", "results", detail=_named(errored)))
        return items

    def _run_activity(self) -> list[ActivityItem]:
        tones = {"passed": "healthy", "failed": "failed", "error": "needs_attention"}
        return [
            ActivityItem("run", f"{run.standard_name} {run.get_status_display().lower()}", run.created_at, "results",
                         tone=tones.get(run.status, ""))
            for run in list(self._results.get("recent_executions") or [])[:RECENT]
            if run.status != StandardExecution.Status.RUNNING
        ]

    # --- Delivery ----------------------------------------------------------------

    def _delivery_attention(self) -> list[AttentionItem]:
        report = self._delivery
        if report is None:
            return []
        items = []
        if report.settings.refresh_error and not report.settings.refreshing:
            items.append(AttentionItem("Delivery data is incomplete", "delivery", detail=report.settings.refresh_error.splitlines()[0]))
        pending = report.pending
        if pending and pending.any and self._now - pending.oldest_at >= STALE:
            items.append(AttentionItem(
                _counted(pending.count, "commit") + " waiting to ship", "delivery",
                detail=f"The oldest has waited {_days(self._now - pending.oldest_at)}.",
            ))
        stale = [pr for pr in report.open_pull_requests if self._now - pr.created_at >= STALE]
        if stale:
            items.append(AttentionItem(
                _counted(len(stale), "pull request") + " open over a week", "delivery",
                detail=_named([f"#{pr.number} {pr.title}" for pr in stale]),
            ))
        if report.has_refreshed and report.frequency.tier is DoraTier.LOW:
            items.append(AttentionItem("Deploys less than once a month", "delivery", detail="DORA deployment frequency: Low."))
        if report.lead_time and report.lead_time.tier is DoraTier.LOW:
            items.append(AttentionItem("Changes take over a month to reach production", "delivery", detail="DORA lead time: Low."))
        return items

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


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _named(names: list[str]) -> str:
    shown = ", ".join(names[:NAMED])
    return shown + (f" and {len(names) - NAMED} more" if len(names) > NAMED else "")


def _days(length: timedelta) -> str:
    days = length.days
    return f"{days} day{'' if days == 1 else 's'}"
