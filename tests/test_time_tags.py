"""Tests for the local_time tag (app/templatetags/time_tags.py)."""
from datetime import datetime, timedelta, timezone

from django.template import Context, Template
from django.test import SimpleTestCase


def render(template, **context):
    return Template("{% load time_tags %}" + template).render(Context(context))


class LocalTimeTagTests(SimpleTestCase):
    def test_keeps_the_format_and_shows_utc_until_the_browser_runs(self):
        # 23:30 in Israel (UTC+2) is 21:30 UTC.
        dt = datetime(2026, 11, 5, 23, 30, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(
            render('{% local_time dt "j M Y, H:i" %}', dt=dt),
            '<time datetime="2026-11-05T21:30:00+00:00" data-localize data-format="j M Y, H:i">5 Nov 2026, 21:30</time>',
        )

    def test_none_renders_nothing(self):
        self.assertEqual(render('{% local_time dt "j M" %}', dt=None), "")

    def test_naive_datetime_is_read_as_utc(self):
        self.assertIn(
            'datetime="2026-11-05T08:30:00+00:00"',
            render('{% local_time dt "j M" %}', dt=datetime(2026, 11, 5, 8, 30)),
        )
