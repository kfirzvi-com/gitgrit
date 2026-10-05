"""Delivery channels: how a notice reaches a person."""

import logging

from django.db import transaction
from django.utils import timezone

from app.domain.models import NotificationDelivery
from app.domain.notifications import Channel, Notice

logger = logging.getLogger(__name__)


class InboxChannel:
    name = "inbox"

    def deliver(
        self, notice: Notice, notification_id: str, recipient_ids: list[str]
    ) -> None:
        """Write one sent inbox row per recipient.

        Repeat rule: a notice with a dedupe_key replaces the recipient's unread
        copies of the same key, so a repeating problem shows once. Read ones stay.
        """
        now = timezone.now()
        with transaction.atomic():
            if notice.dedupe_key:
                NotificationDelivery.objects.filter(
                    channel=self.name,
                    recipient_id__in=recipient_ids,
                    read_at__isnull=True,
                    notification__dedupe_key=notice.dedupe_key,
                    notification__tenant_id=notice.tenant_id,
                ).delete()
            NotificationDelivery.objects.bulk_create(
                NotificationDelivery(
                    notification_id=notification_id,
                    channel=self.name,
                    recipient_id=user_id,
                    status=NotificationDelivery.Status.SENT,
                    sent_at=now,
                )
                for user_id in recipient_ids
            )


class LogChannel:
    """For dev and tests: no person on the other end."""

    name = "log"

    def deliver(
        self, notice: Notice, notification_id: str, recipient_ids: list[str]
    ) -> None:
        logger.info(
            "notification kind=%s tenant=%s title=%r recipients=%d",
            notice.kind,
            notice.tenant_id,
            notice.title,
            len(recipient_ids),
        )


CHANNELS: dict[str, Channel] = {c.name: c for c in (InboxChannel(), LogChannel())}


def channel_for(name: str) -> Channel:
    try:
        return CHANNELS[name]
    except KeyError:
        raise KeyError(
            f"Unknown notification channel {name!r}; known: {sorted(CHANNELS)}"
        ) from None
