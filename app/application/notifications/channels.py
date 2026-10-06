"""Delivery channels: how a notice reaches a person."""

import logging

from django.db import connection, transaction
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
        copies of the same key, so a repeating problem shows once. Read ones
        stay, and so do pinned ones: the recipient asked to keep that copy.

        Two deliveries of one key at the same time (two runs finishing together)
        are serialized with a transaction-scoped advisory lock taken before the
        delete: under READ COMMITTED the second DELETE then starts after the
        first INSERT committed and sees it. Row locks alone would not do that.
        """
        now = timezone.now()
        with transaction.atomic():
            if notice.dedupe_key:
                _lock_key(notice.tenant_id, notice.dedupe_key)
                NotificationDelivery.objects.filter(
                    channel=self.name,
                    recipient_id__in=recipient_ids,
                    read_at__isnull=True,
                    pinned_at__isnull=True,
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


def _lock_key(tenant_id: str, dedupe_key: str) -> None:
    """Hold a Postgres advisory lock for this key until the transaction ends."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", [f"{tenant_id}:{dedupe_key}"]
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
