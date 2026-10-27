import json
from datetime import datetime

from django import template
from django.utils import timezone

register = template.Library()


@register.simple_tag
def json_attr(value):
    """``value`` as JSON for an HTML attribute (``data-x="{% json_attr v %}"``).

    Returned unmarked, so autoescaping turns quotes and ``<`` into entities
    and the browser hands the script the original text. Never put it in a
    <script> block; use the ``json_script`` filter there.
    """
    return json.dumps(value)


@register.filter
def names_json(items):
    """The ``name`` of each item as a JSON list, for an HTML attribute
    (``data-names="{{ things|names_json }}"``); unmarked, like json_attr."""
    return json.dumps([item.name for item in items])


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


_TRIGGER_LABELS = {"manual": "Manual", "pull_request": "Pull request"}


@register.filter
def trigger_label(execution):
    """A readable name for what started a run: 'Manual', 'Pull request',
    'Push', 'Tag'. A push or create whose ref is a tag (webhook refs keep the
    refs/tags/ prefix) reads 'Tag'; a create with any other ref stays
    'Create', since the ref alone cannot say branch from tag."""
    event_type = getattr(execution, "event_type", "") or ""
    ref = getattr(execution, "ref", "") or ""
    if event_type in _TRIGGER_LABELS:
        return _TRIGGER_LABELS[event_type]
    if event_type in ("push", "create"):
        if ref.startswith("refs/tags/"):
            return "Tag"
        return "Push" if event_type == "push" else "Create"
    return event_type.replace("_", " ").capitalize()
