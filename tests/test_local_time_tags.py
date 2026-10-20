"""local_time / local_title render the markup static/app/local-time.js rewrites."""
from datetime import datetime, timezone as dt_timezone

from django.template import Context, Template
from django.test import SimpleTestCase

WHEN = datetime(2026, 6, 6, 15, 7, tzinfo=dt_timezone.utc)
ISO = "2026-06-06T15:07:00+00:00"


def _render(source, **context):
    return Template("{% load project_tags %}" + source).render(Context(context))


class LocalTimeTests(SimpleTestCase):
    def test_each_kind_has_its_format_and_fallback(self):
        cases = {
            "date": "6 Jun 2026",
            "time": "15:07",
            "full": "6 Jun 2026, 15:07 UTC",
        }
        for kind, text in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(
                    _render(f'{{% local_time when "{kind}" %}}', when=WHEN),
                    f'<time datetime="{ISO}" data-local-time data-time-format="{kind}">{text}</time>',
                )

    def test_default_kind_has_no_format_attribute(self):
        expected = f'<time datetime="{ISO}" data-local-time>6 Jun 2026, 15:07</time>'
        self.assertEqual(_render("{% local_time when %}", when=WHEN), expected)
        self.assertEqual(_render('{% local_time when "datetime" %}', when=WHEN), expected)

    def test_css_class(self):
        self.assertEqual(
            _render('{% local_time when "datetime" "text-xs" %}', when=WHEN),
            f'<time datetime="{ISO}" data-local-time class="text-xs">6 Jun 2026, 15:07</time>',
        )

    def test_log_kind_uses_the_log_time_filter(self):
        self.assertEqual(
            _render('{% local_time ts "log" %}', ts="2026-06-06T15:07:47.489+00:00"),
            '<time datetime="2026-06-06T15:07:47.489+00:00" data-local-time data-time-format="log">'
            "Jun 6, 2026 3:07:47.489 PM UTC</time>",
        )

    def test_iso_string_is_used_as_the_datetime_attribute(self):
        self.assertEqual(
            _render('{% local_time ts "date" %}', ts=ISO),
            f'<time datetime="{ISO}" data-local-time data-time-format="date">6 Jun 2026</time>',
        )

    def test_empty_value_renders_nothing(self):
        for empty in (None, ""):
            with self.subTest(empty=empty):
                self.assertEqual(_render('{% local_time v "date" %}', v=empty), "")
                self.assertEqual(_render("{% local_title v %}", v=empty), "")

    def test_local_title_attributes(self):
        self.assertEqual(
            _render("<div{% local_title when %}>x</div>", when=WHEN),
            f'<div data-local-title="{ISO}" title="6 Jun 2026, 15:07 UTC">x</div>',
        )
