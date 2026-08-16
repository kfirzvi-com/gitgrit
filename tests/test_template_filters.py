"""Tests for custom template filters."""
from django.test import SimpleTestCase

from app.templatetags.project_tags import log_time


class LogTimeTests(SimpleTestCase):
    def test_formats_iso_as_friendly_datetime(self):
        # TIME_ZONE is UTC in tests, so local time equals the input.
        self.assertEqual(
            log_time("2026-06-06T15:17:47.489+00:00"),
            "Jun 6, 2026 3:17:47.489 PM UTC",
        )

    def test_handles_midnight_and_noon(self):
        self.assertEqual(
            log_time("2026-06-06T00:00:00.000+00:00"),
            "Jun 6, 2026 12:00:00.000 AM UTC",
        )
        self.assertEqual(
            log_time("2026-06-06T12:00:00.000+00:00"),
            "Jun 6, 2026 12:00:00.000 PM UTC",
        )

    def test_falls_back_on_bad_input(self):
        self.assertEqual(log_time(""), "")
        self.assertEqual(log_time(None), "")
        self.assertEqual(log_time("not-a-timestamp"), "not-a-timestamp")
