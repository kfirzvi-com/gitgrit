from __future__ import annotations

from datetime import datetime
from typing import Callable

from django.utils import timezone

from app.application.delivery.deployment_refresh import DeploymentRefresh, SourcesFor
from app.models import DeliverySettings, Project


class DeliverySync:
    """Reads a project's delivery data from its Git platform and stores it:
    its deployments (and the strategy that found them). Whatever could not
    be read is noted on the settings for the Delivery tab to show; what was
    stored before stays."""

    def __init__(self, sources_for: SourcesFor, now: Callable[[], datetime] = timezone.now):
        self._deployments = DeploymentRefresh(sources_for, now)
        self._now = now

    def run(self, project: Project) -> DeliverySettings:
        settings, _ = DeliverySettings.objects.get_or_create(project=project)
        problems: list[str] = []
        strategy = self._deployments.run(project, settings, problems)
        if strategy is not None:
            settings.detected_strategy = strategy.value
        settings.refreshed_at = self._now()
        settings.refresh_error = "\n".join(dict.fromkeys(problems))
        settings.save(update_fields=["detected_strategy", "refreshed_at", "refresh_error", "updated_at"])
        return settings
