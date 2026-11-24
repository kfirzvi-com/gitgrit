from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import F, Q, QuerySet

from app.domain.delivery import SyncPolicy
from app.models import Platform, Project


class DeliverySyncSchedule:
    """Which projects are due a scheduled delivery sync. The interval is
    ``GITGRIT_DELIVERY_SYNC_MINUTES`` (15 by default)."""

    @staticmethod
    def policy() -> SyncPolicy:
        return SyncPolicy(interval=timedelta(minutes=settings.GITGRIT_DELIVERY_SYNC_MINUTES))

    @classmethod
    def due(cls, now: datetime) -> QuerySet[Project]:
        """Git projects never synced, or last synced at least an interval
        ago. One asked for within the interval and still under way is left
        alone; one asked for longer ago than that is asked for again, in
        case its job was lost. Uploaded builds have nothing to sync."""
        cutoff = now - cls.policy().interval
        under_way = Q(delivery__refresh_requested_at__gt=cutoff) & (
            Q(delivery__refreshed_at__isnull=True)
            | Q(delivery__refreshed_at__lt=F("delivery__refresh_requested_at"))
        )
        return (
            Project.objects.exclude(platform=Platform.ARTIFACT)
            .filter(
                Q(delivery__isnull=True)
                | Q(delivery__refreshed_at__isnull=True)
                | Q(delivery__refreshed_at__lte=cutoff)
            )
            .exclude(under_way)
        )
