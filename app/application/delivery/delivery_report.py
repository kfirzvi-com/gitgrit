from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from app.domain.delivery import DeploymentFrequency, DeploymentStrategy
from app.models import DeliverySettings, Deployment, Project

RECENT = 10


@dataclass(frozen=True)
class DeliveryReport:
    """What the project page shows about delivery: the strategy in use, how
    often the project ships and its latest deployments (failed ones too)."""

    settings: DeliverySettings
    strategy: DeploymentStrategy | None
    frequency: DeploymentFrequency
    recent: tuple[Deployment, ...]

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
        frequency = DeploymentFrequency.of(
            (deployment.event for deployment in deployments), now.date(), tz=now.tzinfo
        )
        return cls(
            settings=settings,
            strategy=strategy,
            frequency=frequency,
            recent=tuple(deployments.order_by("-deployed_at")[:RECENT]),
        )

    @property
    def has_refreshed(self) -> bool:
        return self.settings.refreshed_at is not None
