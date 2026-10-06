"""Delivery channels: how a notice reaches a person."""

import logging

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

        Every delivery is its own row: a repeat of the same problem (another
        run of the same project failing the same standards) shows as a new
        notification rather than replacing the earlier one.
        """
        now = timezone.now()
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
