import json
from datetime import datetime

from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def to_json(value):
    return mark_safe(json.dumps(value))


@register.filter
def log_time(value):
    """Render an ISO 8601 execution-log timestamp as a friendly, space-separated
    'date time timezone', e.g. 'Jun 6, 2026 3:17:47.489 PM UTC'. Falls back to
    the raw value if it can't be parsed."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    try:
        dt = timezone.localtime(dt)
    except (ValueError, OverflowError):
        pass  # naive datetime / no tz — render as-is
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    date_part = f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    time_part = f"{hour}:{dt.minute:02d}:{dt.second:02d}.{dt.microsecond // 1000:03d} {ampm}"
    tz = dt.tzname() or ""
    return f"{date_part} {time_part} {tz}".strip()
