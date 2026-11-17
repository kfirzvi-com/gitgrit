"""A user's time zone (app.domain.user_time_zone): asking for it once, and the
user changing it. Only the user does this, from their Profile or the
question: there is no way to set someone else's."""
from django.db import transaction
from django.utils import timezone

from app.application.notifications.service import raise_notification
from app.domain.models import Notification, User
from app.domain.user_time_zone import UserTimeZone


def change_time_zone(user: User, name: str) -> UserTimeZone:
    """Save ``name`` as ``user``'s time zone, or raise ``UnknownTimeZone``
    and save nothing."""
    zone = UserTimeZone.parse(name)
    user.time_zone = zone.name
    user.save(update_fields=["time_zone"])
    return zone


def ask_for_time_zone(user: User, device_zone: str, tenant_id) -> UserTimeZone | None:
    """Ask ``user`` for their time zone, once (rule 6): the zone to suggest
    (``device_zone``), or None when there is nothing to ask. Asking also puts
    a note in the user's notification center in ``tenant_id`` (none without a
    workspace). Either way the user counts as asked, so it never repeats."""
    if not user.should_be_asked_time_zone:
        return None
    suggestion = UserTimeZone.suggestion_for(device_zone)
    with transaction.atomic():
        # Only the first of two tabs asking at once marks the user and notifies.
        now = timezone.now()
        marked = User.objects.filter(pk=user.pk, time_zone_asked_at__isnull=True).update(
            time_zone_asked_at=now
        )
        if not marked:
            return None
        user.time_zone_asked_at = now
        if suggestion is not None and tenant_id is not None:
            raise_notification(Notification.time_zone_not_chosen(tenant_id=tenant_id, user=user))
    return suggestion
