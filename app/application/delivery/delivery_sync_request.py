from __future__ import annotations

import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from procrastinate.exceptions import AlreadyEnqueued

from app.application.delivery.delivery_sync_schedule import DeliverySyncSchedule
from app.models import DeliverySettings, Project

logger = logging.getLogger(__name__)


class DeliverySyncRequest:
    """Asks the worker to sync a project's delivery data. Requests for the
    same project coalesce while one is queued, and the settings remember the
    request so the page can show it is under way."""

    @staticmethod
    def send(project: Project) -> DeliverySettings:
        from app.tasks import sync_delivery

        settings, _ = DeliverySettings.objects.get_or_create(project=project)
        settings.refresh_requested_at = timezone.now()
        settings.save(update_fields=["refresh_requested_at", "updated_at"])
        try:
            with transaction.atomic():
                sync_delivery.configure(
                    lock=f"delivery:{project.pk}",
                    queueing_lock=f"delivery:{project.pk}",
                ).defer(project_id=str(project.pk))
        except AlreadyEnqueued:
            logger.debug("delivery sync already queued for project %s", project.pk)
        return settings

    @classmethod
    def refresh(cls, project: Project, now: datetime | None = None) -> bool:
        """A sync asked for by hand: sent unless the last one was too recent
        (``SyncPolicy.cooldown``). Says whether it was sent."""
        settings, _ = DeliverySettings.objects.get_or_create(project=project)
        if settings.refreshing:
            return False
        if not DeliverySyncSchedule.policy().may_refresh(settings.refreshed_at, now or timezone.now()):
            return False
        cls.send(project)
        return True
