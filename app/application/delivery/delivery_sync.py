from __future__ import annotations

from datetime import datetime
from typing import Callable

from django.utils import timezone

from app.application.delivery.deployment_refresh import DeploymentRefresh, SourcesFor
from app.application.delivery.repository_activity import RepositoryActivity
from app.application.delivery.source_unavailable import SourceUnavailable
from app.domain.delivery import RunningVersion
from app.models import DeliverySettings, Deployment, Project

ActivityFor = Callable[[Project], RepositoryActivity]


class DeliverySync:
    """Reads a project's delivery data from its Git platform and stores it:
    its deployments (and the strategy that found them) and the commits on
    the default branch that the running version lacks. Whatever could not
    be read is noted on the settings for the Delivery tab to show; what was
    stored before stays."""

    def __init__(
        self,
        sources_for: SourcesFor,
        activity_for: ActivityFor | None = None,
        now: Callable[[], datetime] = timezone.now,
    ):
        self._deployments = DeploymentRefresh(sources_for, now)
        self._activity_for = activity_for
        self._now = now

    def run(self, project: Project) -> DeliverySettings:
        settings, _ = DeliverySettings.objects.get_or_create(project=project)
        problems: list[str] = []
        strategy = self._deployments.run(project, settings, problems)
        if strategy is not None:
            settings.detected_strategy = strategy.value
        if self._activity_for is not None:
            self._sync_pending(project, settings, problems)
        settings.refreshed_at = self._now()
        settings.refresh_error = "\n".join(dict.fromkeys(problems))
        settings.save(
            update_fields=[
                "detected_strategy",
                "pending_commits",
                "oldest_pending_at",
                "refreshed_at",
                "refresh_error",
                "updated_at",
            ]
        )
        return settings

    def _sync_pending(self, project: Project, settings: DeliverySettings, problems: list[str]) -> None:
        strategy = settings.strategy_in_use
        running = RunningVersion.latest(
            deployment.event for deployment in Deployment.objects.filter(project=project, strategy=strategy)
        ) if strategy else None
        if running is None or not project.default_branch:
            settings.pending_commits = settings.oldest_pending_at = None
            return
        try:
            pending = self._activity_for(project).pending_commits(running.sha, project.default_branch)
        except SourceUnavailable as unavailable:
            problems.append(str(unavailable))
            return
        settings.pending_commits = pending.count if pending else None
        settings.oldest_pending_at = pending.oldest_at if pending else None
