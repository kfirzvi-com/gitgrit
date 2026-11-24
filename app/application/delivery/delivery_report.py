from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from app.domain.delivery import (
    DeploymentFrequency,
    DeploymentStrategy,
    PendingCommits,
    PullRequestFlow,
    PullRequestState,
    RunningVersion,
)
from app.domain.delivery.deployment_frequency import WEEKS
from app.models import DeliverySettings, Deployment, Project, PullRequest

RECENT = 10
# Open pull requests listed on the tab, oldest first; the rest are a link away.
OPEN_LISTED = 25


@dataclass(frozen=True)
class DeliveryReport:
    """What the project page shows about delivery: what runs in production
    and what waits to ship, the strategy in use, how often the project ships,
    its latest deployments (failed ones too) and how its pull requests flow."""

    settings: DeliverySettings
    strategy: DeploymentStrategy | None
    frequency: DeploymentFrequency
    recent: tuple[Deployment, ...]
    running: RunningVersion | None = None
    pull_requests: PullRequestFlow | None = None
    open_pull_requests: tuple[PullRequest, ...] = ()

    @classmethod
    def for_project(cls, project: Project, now: datetime | None = None) -> DeliveryReport:
        settings, _ = DeliverySettings.objects.get_or_create(project=project)
        now = timezone.localtime(now or timezone.now())
        strategy = settings.strategy_in_use
        deployments = (
            Deployment.objects.filter(project=project, strategy=strategy.value)
            if strategy
            else Deployment.objects.none()
        )
        events = [deployment.event for deployment in deployments]
        pulls = cls._pull_requests_in_window(project, now)
        return cls(
            settings=settings,
            strategy=strategy,
            frequency=DeploymentFrequency.of(events, now.date(), tz=now.tzinfo),
            recent=tuple(deployments.order_by("-deployed_at")[:RECENT]),
            running=RunningVersion.latest(events),
            pull_requests=PullRequestFlow.of((pr.facts for pr in pulls), now.date(), tz=now.tzinfo, now=now),
            open_pull_requests=tuple(
                pulls.filter(state=PullRequestState.OPEN).order_by("created_at")[:OPEN_LISTED]
            ),
        )

    @staticmethod
    def _pull_requests_in_window(project: Project, now: datetime):
        """Pull requests open at some point in the window: still open, or
        closed within it (the window is under 14 weeks)."""
        window_start = now - timedelta(weeks=WEEKS)
        return PullRequest.objects.filter(project=project).filter(
            Q(closed_at__isnull=True) | Q(closed_at__gte=window_start)
        )

    @property
    def pending(self) -> PendingCommits | None:
        return self.settings.pending

    @property
    def has_refreshed(self) -> bool:
        return self.settings.refreshed_at is not None
