from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from django.utils import timezone

from app.application.delivery.deployment_sources import DeploymentSources
from app.application.delivery.source_unavailable import SourceUnavailable
from app.domain.delivery import DeploymentEvent, DeploymentStrategy
from app.domain.delivery.deployment_frequency import WEEKS
from app.models import DeliverySettings, Deployment, Project

# A week more than the frequency window, so a refresh late on the window's
# first day still has all of it.
LOOKBACK = timedelta(weeks=WEEKS + 1)

SourcesFor = Callable[[Project, DeliverySettings], DeploymentSources]


class DeploymentRefresh:
    """Looks for a project's deployments with its strategy (or, set to
    detect, with the first strategy that finds any) and records them.
    Recording is idempotent: a deployment found again updates in place."""

    def __init__(self, sources_for: SourcesFor, now: Callable[[], datetime] = timezone.now):
        self._sources_for = sources_for
        self._now = now

    def run(self, project: Project) -> DeliverySettings:
        settings, _ = DeliverySettings.objects.get_or_create(project=project)
        since = self._now() - LOOKBACK
        problems: list[str] = []
        strategy: DeploymentStrategy | None = None
        try:
            sources = self._sources_for(project, settings)
            strategy, events = self._find(sources, settings, since, problems)
            self._record(project, events)
        except SourceUnavailable as unavailable:
            problems.append(str(unavailable))
        settings.detected_strategy = strategy.value if strategy else ""
        settings.refreshed_at = self._now()
        settings.refresh_error = "\n".join(problems)
        settings.save(update_fields=["detected_strategy", "refreshed_at", "refresh_error", "updated_at"])
        return settings

    def _find(
        self, sources: DeploymentSources, settings: DeliverySettings, since: datetime, problems: list[str]
    ) -> tuple[DeploymentStrategy, list[DeploymentEvent]]:
        if settings.strategy != DeploymentStrategy.AUTO:
            chosen = DeploymentStrategy(settings.strategy)
            return chosen, sources.for_strategy(chosen).find(since)
        order = DeploymentStrategy.detection_order()
        for strategy in order[:-1]:
            try:
                events = sources.for_strategy(strategy).find(since)
            except SourceUnavailable as unavailable:
                problems.append(str(unavailable))
                continue
            if any(event.succeeded for event in events):
                return strategy, events
        fallback = order[-1]
        return fallback, sources.for_strategy(fallback).find(since)

    def _record(self, project: Project, events: list[DeploymentEvent]) -> None:
        Deployment.objects.bulk_create(
            [
                Deployment(
                    project=project,
                    strategy=event.strategy.value,
                    external_id=event.external_id,
                    sha=event.sha,
                    ref=event.ref,
                    environment=event.environment,
                    deployed_at=event.deployed_at,
                    succeeded=event.succeeded,
                )
                for event in events
            ],
            update_conflicts=True,
            unique_fields=["project", "strategy", "external_id"],
            update_fields=["sha", "ref", "environment", "deployed_at", "succeeded"],
        )
