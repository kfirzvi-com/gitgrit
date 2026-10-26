"""Deliver one stored notification on every channel its route names.

Runs in the ``deliver_notification`` job. Channels are independent: one that
raises gets a FAILED log row and the others still run. Safe to re-run: a
channel that already has a SENT log row is skipped, and each channel's
delivery and its SENT row commit together, so a retry after a crashed worker
never delivers twice.
"""

import logging

from django.db import transaction

from app.domain.limits import MAX_ERROR_TEXT
from app.domain.models import DeliveryLog, Notification
from app.domain.notifications.channels import Channel, InboxChannel
from app.domain.notifications.notification_routing import route_for

logger = logging.getLogger(__name__)

# The channels plugged in, by the name routes use. An adapter for an outside
# system (email, GitHub Checks) is added here from app.infrastructure.
CHANNELS: dict[str, Channel] = {c.name: c for c in (InboxChannel(),)}


def channel_for(name: str) -> Channel:
    try:
        return CHANNELS[name]
    except KeyError:
        raise KeyError(
            f"Unknown notification channel {name!r}; known: {sorted(CHANNELS)}"
        ) from None


def dispatch(notification_id: str) -> None:
    notification = Notification.objects.filter(pk=notification_id).first()
    if notification is None:
        logger.warning("dispatch: notification %s no longer exists", notification_id)
        return

    route = route_for(notification.kind)
    recipients = route.recipients(notification)
    already_sent = set(
        notification.delivery_logs.filter(status=DeliveryLog.Status.SENT).values_list(
            "channel", flat=True
        )
    )
    for name in route.channels:
        if name in already_sent:
            continue
        try:
            with transaction.atomic():
                channel_for(name).deliver(notification, recipients)
                DeliveryLog.objects.create(
                    notification=notification, channel=name, status=DeliveryLog.Status.SENT
                )
        except Exception as exc:
            logger.exception("notification %s: channel %s failed", notification_id, name)
            DeliveryLog.objects.create(
                notification=notification,
                channel=name,
                status=DeliveryLog.Status.FAILED,
                error=str(exc)[:MAX_ERROR_TEXT],
            )
