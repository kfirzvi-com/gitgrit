"""A schedule's time zone belongs to the schedule: its chip names the zone,
and the editor's reading gives its times in it, plus the viewer's own when
their zone is another."""
from datetime import datetime, timezone

from django.test import SimpleTestCase

from app.domain import schedules
from app.presentation.schedule_chip import ScheduleChip
from app.presentation.schedule_preview import SchedulePreview
from app.presentation.time_zone_label import TimeZoneLabel

# A Monday, 21:00 UTC (22:00 in Madrid).
NOW = datetime(2026, 11, 23, 21, 0, tzinfo=timezone.utc)


class TimeZoneLabelTests(SimpleTestCase):
    def test_a_zone_is_named_by_its_place(self):
        self.assertEqual(TimeZoneLabel("Europe/Madrid").text, "Madrid")
        self.assertEqual(TimeZoneLabel("America/New_York").text, "New York")
        self.assertEqual(TimeZoneLabel("America/Argentina/Buenos_Aires").text, "Buenos Aires")
        self.assertEqual(TimeZoneLabel("UTC").text, "UTC")
        self.assertEqual(TimeZoneLabel("").text, "")


class ScheduleChipZoneTests(SimpleTestCase):
    def test_a_schedule_shows_its_own_zone(self):
        chip = ScheduleChip.of(schedules.StandardSchedule.parse("schedule", "0 6 * * 1-5", "Europe/Madrid"), "Asia/Tokyo")
        self.assertEqual(chip.label, "At 06:00 on weekdays")
        self.assertEqual(chip.time_zone, "Europe/Madrid")
        self.assertEqual(chip.zone_label, "Madrid")

    def test_no_schedule_starts_in_the_default_zone_and_names_none(self):
        chip = ScheduleChip.of(schedules.StandardSchedule(), "Asia/Tokyo")
        self.assertEqual(chip.time_zone, "Asia/Tokyo")
        self.assertEqual(chip.zone_label, "")

    def test_no_schedule_and_no_default_leaves_the_zone_to_the_browser(self):
        self.assertEqual(ScheduleChip.of(schedules.StandardSchedule()).time_zone, "")


class SchedulePreviewViewerTests(SimpleTestCase):
    def test_times_are_the_schedules_and_the_viewers_own_beside_them(self):
        data = SchedulePreview("0 6 * * 1-5", "Europe/Madrid", "America/New_York").as_dict(NOW)
        self.assertEqual(data["time_zone"], "Europe/Madrid")
        self.assertEqual(data["next_runs"][0], "Tue 24 Nov, 06:00")
        self.assertEqual(data["viewer_time_zone"], "America/New_York")
        self.assertEqual(data["viewer_next_runs"][0], "Tue 24 Nov, 00:00")

    def test_a_viewer_in_the_schedules_zone_gets_no_second_line(self):
        data = SchedulePreview("0 6 * * 1-5", "Europe/Madrid", "Europe/Madrid").as_dict(NOW)
        self.assertEqual(data["viewer_next_runs"], [])
        self.assertEqual(data["viewer_time_zone"], "")

    def test_an_unknown_viewer_zone_is_ignored(self):
        data = SchedulePreview("0 6 * * 1-5", "Europe/Madrid", "Not/AZone").as_dict(NOW)
        self.assertTrue(data["valid"])
        self.assertEqual(data["viewer_next_runs"], [])

    def test_an_unknown_schedule_zone_is_refused(self):
        data = SchedulePreview("0 6 * * 1-5", "Not/AZone").as_dict(NOW)
        self.assertFalse(data["valid"])
