"""Times shown in the viewer's own time zone. The server writes the time in
UTC; ``static/app/local-time.js`` (loaded in base.html) rewrites it in the
browser's zone, in the same format.

    {% load time_tags %}
    {% local_time run.created_at "j M Y, H:i" %}   {# the template's own Django format #}

The JS knows only the letters j d m M N F Y y H i P.
"""

from datetime import timezone as dt_timezone

from django import template
from django.utils import dateformat
from django.utils.timesince import timesince
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def local_time(value, fmt):
    """``<time datetime="<UTC ISO>" data-localize data-format="<fmt>">``, with
    the time in UTC as the text until the browser rewrites it. ``None``
    renders nothing."""
    if value is None:
        return ""
    if value.tzinfo is None:  # e.g. a commit date parsed without an offset: stored times are UTC
        value = value.replace(tzinfo=dt_timezone.utc)
    utc = value.astimezone(dt_timezone.utc)
    return format_html(
        '<time datetime="{}" data-localize data-format="{}">{}</time>',
        utc.isoformat(),
        fmt,
        dateformat.format(utc, fmt),
    )


@register.filter
def ago(value):
    """How long ago ``value`` was, in its largest unit only: "16 hours ago",
    where ``timesince`` says "16 hours, 58 minutes"."""
    if not value:
        return ""
    return f"{timesince(value, depth=1)} ago"


@register.filter
def duration(value):
    """A length of time (a ``timedelta``) as a person says it: "45 minutes",
    "3.2 hours", "1.5 days", "6 weeks"; "—" when there is none."""
    if value is None:
        return "—"
    minutes = value.total_seconds() / 60
    if minutes < 60:
        return f"{max(round(minutes), 1):g} minute{'' if round(minutes) == 1 else 's'}"
    hours = minutes / 60
    if hours < 24:
        return f"{_tenths(hours)} hour{'' if hours == 1 else 's'}"
    days = hours / 24
    if days < 14:
        return f"{_tenths(days)} day{'' if days == 1 else 's'}"
    return f"{_tenths(days / 7)} weeks"


def _tenths(number: float) -> str:
    return f"{round(number, 1):g}"


@register.filter
def short_duration(value):
    """A length of time in a few characters, for tight spaces: "45m",
    "19.6h", "3.5d", "6w"; "—" when there is none."""
    if value is None:
        return "—"
    minutes = value.total_seconds() / 60
    if minutes < 60:
        return f"{max(round(minutes), 1)}m"
    hours = minutes / 60
    if hours < 24:
        return f"{_tenths(hours)}h"
    days = hours / 24
    if days < 14:
        return f"{_tenths(days)}d"
    return f"{_tenths(days / 7)}w"
