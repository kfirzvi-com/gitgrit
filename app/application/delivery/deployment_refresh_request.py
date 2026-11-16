from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from procrastinate.exceptions import AlreadyEnqueued

from app.models import DeliverySettings, Project

logger = logging.getLogger(__name__)


class DeploymentRefreshRequest:
    """Asks the worker to look for a project's deployments. Requests for the
    same project coalesce while one is queued, and the settings remember
    the request so the page can show it is under way."""

    @staticmethod
    def send(project: Project) -> DeliverySettings:
        from app.tasks import refresh_deployments

        settings, _ = DeliverySettings.objects.get_or_create(project=project)
        settings.refresh_requested_at = timezone.now()
        settings.save(update_fields=["refresh_requested_at", "updated_at"])
        try:
            with transaction.atomic():
                refresh_deployments.configure(
                    lock=f"deployments:{project.pk}",
                    queueing_lock=f"deployments:{project.pk}",
                ).defer(project_id=str(project.pk))
        except AlreadyEnqueued:
            logger.debug("deployment refresh already queued for project %s", project.pk)
        return settings
