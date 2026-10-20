import json
from datetime import datetime

from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

from app.domain import levels

register = template.Library()


@register.simple_tag
def level_rules():
    """Every standard level's rule (``app.domain.levels``), most severe
    first: the options, bulk actions and filter of the standards table."""
    return levels.ordered_rules()


@register.filter
def level_of(levels_by_standard, standard_id):
    """The level ``standard_id`` has in ``levels_by_standard`` (a dict),
    the default level when it has none."""
    return (levels_by_standard or {}).get(standard_id, levels.DEFAULT_LEVEL.value)


@register.filter
def level_help(level):
    """The one-line tooltip of a level value, from its rule."""
    return levels.rule_for(level).help


@register.simple_tag
def critical_levels_help():
    """The tooltip of the "N critical failed" count: what each level shown
    as critical does, from its rule."""
    return " ".join(
        f"{r.label}: {r.help}." for r in levels.ordered_rules() if r.shown_as_critical
    )


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


@register.filter
def short_date(value):
    """A date as a date, never "3 days ago": 'H:i' when it is today (in the
    active timezone), else 'j M Y', e.g. '14:09' or '12 Oct 2026'."""
    if not value:
        return ""
    value = timezone.localtime(value) if timezone.is_aware(value) else value
    today = timezone.localdate()
    return value.strftime("%H:%M") if value.date() == today else f"{value.day} {value:%b %Y}"


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
