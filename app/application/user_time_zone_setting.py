"""A user's time zone (app.domain.user_time_zone): asking for it once, and the
user changing it. Only the user does this, from their Profile or the
question: there is no way to set someone else's. Others hear about it through
events (``TimeZoneAsked``, ``TimeZoneChosen``); this module knows nothing
about them."""
from django.db import transaction
from django.utils import timezone

from app.application.event_bus import publish
from app.domain.events import TimeZoneAsked, TimeZoneChosen
from app.domain.models import User
from app.domain.user_time_zone import UserTimeZone


def change_time_zone(user: User, name: str) -> UserTimeZone:
    """Save ``name`` as ``user``'s time zone, or raise ``UnknownTimeZone``
    and save nothing."""
    zone = UserTimeZone.parse(name)
    user.time_zone = zone.name
    user.save(update_fields=["time_zone"])
    _announce_after_save(TimeZoneChosen(user_id=str(user.pk)))
    return zone


def ask_for_time_zone(user: User, device_zone: str) -> UserTimeZone | None:
    """Ask ``user`` for their time zone, once (rule 6): the zone to suggest
    (``device_zone``), or None when there is nothing to ask (already asked or
    chosen, or the device is on UTC or an unknown zone). The user counts as
    asked from here on, even if the question never reaches the page (a closed
    tab): asking is once, not until seen."""
    if not user.should_be_asked_time_zone:
        return None
    suggestion = UserTimeZone.suggestion_for(device_zone)
    with transaction.atomic():
        now = timezone.now()
        # Only the first of two tabs asking at once marks the user asked.
        marked = User.objects.filter(pk=user.pk, time_zone_asked_at__isnull=True).update(
            time_zone_asked_at=now
        )
        if not marked:
            return None
        user.time_zone_asked_at = now
        if suggestion is not None:
            _announce_after_save(TimeZoneAsked(user_id=str(user.pk)))
    return suggestion


def _announce_after_save(event) -> None:
    """Tell listeners once the user's change is saved, so nothing a listener
    does (or fails to do) can undo it."""
    transaction.on_commit(lambda: publish(event))
