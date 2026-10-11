"""``raise_notification()``: the one way a notification enters the system."""

from django.db import transaction

from app.domain.models import Notification


def raise_notification(notification: Notification) -> Notification:
    """Store a new notification and queue its delivery, in one transaction.

    Both rows exist or neither does (transactional outbox): a notification
    is never stored without being delivered, and the delivery job never runs
    for a notification that was not stored. The job carries only the id and
    re-reads the row. Procrastinate keeps its jobs in the same Postgres, so
    one commit covers both.
    """
    if not notification._state.adding:
        raise ValueError("A notification is raised once; this one is already stored.")

    # Imported lazily: app.tasks pulls in application code, and this module
    # must stay importable from anywhere without a cycle.
    from app.tasks import deliver_notification

    with transaction.atomic():
        notification.save()
        deliver_notification.defer(notification_id=str(notification.pk))
    return notification
