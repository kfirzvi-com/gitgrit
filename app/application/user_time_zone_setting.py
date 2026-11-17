"""A user changing their own time zone (app.domain.user_time_zone). Only the
user does this, from their Profile: there is no way to set someone else's."""
from app.domain.models import User
from app.domain.user_time_zone import UserTimeZone


def change_time_zone(user: User, name: str) -> UserTimeZone:
    """Save ``name`` as ``user``'s time zone, or raise ``UnknownTimeZone``
    and save nothing."""
    zone = UserTimeZone.parse(name)
    user.time_zone = zone.name
    user.save(update_fields=["time_zone"])
    return zone
