"""Tests for custom template filters."""
from app.templatetags.project_tags import log_time


def test_log_time_formats_iso_as_friendly_datetime():
    # TIME_ZONE is UTC in tests, so local time equals the input.
    assert log_time("2026-06-06T15:17:47.489+00:00") == "Jun 6, 2026 3:17:47.489 PM UTC"


def test_log_time_handles_midnight_and_noon():
    assert log_time("2026-06-06T00:00:00.000+00:00") == "Jun 6, 2026 12:00:00.000 AM UTC"
    assert log_time("2026-06-06T12:00:00.000+00:00") == "Jun 6, 2026 12:00:00.000 PM UTC"


def test_log_time_falls_back_on_bad_input():
    assert log_time("") == ""
    assert log_time(None) == ""
    assert log_time("not-a-timestamp") == "not-a-timestamp"
