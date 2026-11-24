from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.application.delivery.delivery_summary import DeliverySummary
from app.domain.delivery import DeliveryTotals
from app.models import Platform, Project, Tenant

# Latest deployments listed on the dashboard.
LATEST = 8


@dataclass(frozen=True)
class WorkspaceDelivery:
    """The dashboard's Delivery tab: a workspace's delivery summed over its
    synced Git projects, and which projects deployed most recently."""

    totals: DeliveryTotals
    latest: tuple[tuple[Project, DeliverySummary], ...]
    synced: int
    projects: int

    @classmethod
    def for_workspace(cls, tenant: Tenant, now: datetime | None = None) -> WorkspaceDelivery:
        projects = list(Project.objects.filter(tenant=tenant).exclude(platform=Platform.ARTIFACT))
        summaries = DeliverySummary.for_projects(projects, now)
        synced = [(project, summaries[project.pk]) for project in projects if summaries[project.pk].synced]
        deployed = sorted(
            ((project, summary) for project, summary in synced if summary.running),
            key=lambda row: row[1].running.deployed_at,
            reverse=True,
        )
        return cls(
            totals=DeliveryTotals.of(
                [summary.frequency for _, summary in synced], [summary.pull_requests for _, summary in synced]
            ),
            latest=tuple(deployed[:LATEST]),
            synced=len(synced),
            projects=len(projects),
        )
