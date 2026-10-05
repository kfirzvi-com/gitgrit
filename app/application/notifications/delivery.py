"""Deliver one stored Notification on every channel its rule names.

Runs in the ``deliver_notification`` job. Channels are independent: one
raising is logged and recorded as a ``failed`` row, and the others still run.
Safe to re-run: a channel that already has a ``sent`` row for the
notification is skipped, so a retry after a worker crash never double-posts.
"""

import logging

from app.application.notifications.audience import resolve
from app.application.notifications.channels import channel_for
from app.application.notifications.router import rule_for
from app.domain.models import Notification, NotificationDelivery
from app.domain.notifications import Notice, Severity

logger = logging.getLogger(__name__)


def notice_from_row(row: Notification) -> Notice:
    """Rebuild the Notice that notify() stored; mentions travel in ``context``."""
    context = dict(row.context)
    mentioned = tuple(str(u) for u in context.pop("mentioned_user_ids", ()))
    return Notice(
        kind=row.kind,
        tenant_id=str(row.tenant_id),
        severity=Severity(row.severity),
        title=row.title,
        body=row.body,
        url=row.url,
        context=context,
        dedupe_key=row.dedupe_key or None,
        mentioned_user_ids=mentioned,
    )


def deliver(notification_id: str) -> None:
    row = Notification.objects.filter(pk=notification_id).first()
    if row is None:
        logger.warning("deliver: notification %s no longer exists", notification_id)
        return

    notice = notice_from_row(row)
    rule = rule_for(notice.kind)
    recipient_ids = resolve(rule.audience, notice.tenant_id, notice.mentioned_user_ids)
    already_sent = set(
        NotificationDelivery.objects.filter(
            notification=row, status=NotificationDelivery.Status.SENT
        ).values_list("channel", flat=True)
    )
    for name in rule.channels:
        if name in already_sent:
            continue
        try:
            channel_for(name).deliver(notice, notification_id, recipient_ids)
        except Exception as exc:
            logger.exception(
                "notification %s: channel %s failed", notification_id, name
            )
            NotificationDelivery.objects.create(
                notification=row,
                channel=name,
                status=NotificationDelivery.Status.FAILED,
                error=str(exc)[:2000],
                recipient=None,
            )
