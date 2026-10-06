"""The notification center's single entry point: ``notify()``.

Sources (anything that has something to report) call ``notify()``; channels
never do. The row and its delivery job are written in one transaction, so a
notice is either stored and queued, or not there at all.
"""

from django.db import transaction

from app.domain.notifications import Notice


def notify(notice: Notice) -> str:
    """Store the notice and queue its delivery; returns the Notification id."""
    # Imported lazily: app.tasks pulls in application code, and this package
    # must stay importable from anywhere without a cycle.
    from app.domain.models import Notification
    from app.tasks import deliver_notification

    # A title carries a project name that may itself fill the column; cut it
    # rather than lose the whole notice to a DataError nobody sees.
    title_max = Notification._meta.get_field("title").max_length
    with transaction.atomic():
        row = Notification.objects.create(
            tenant_id=notice.tenant_id,
            kind=notice.kind,
            severity=notice.severity,
            title=notice.title[:title_max],
            body=notice.body,
            url=notice.url,
            # Mentions ride in context so the model needs no extra column.
            context={
                **notice.context,
                "mentioned_user_ids": [str(u) for u in notice.mentioned_user_ids],
            },
            dedupe_key=notice.dedupe_key or "",
        )
        deliver_notification.defer(notification_id=str(row.id))
    return str(row.id)
