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
