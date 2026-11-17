"""A user's time zone (app.domain.user_time_zone): one test class per rule,
named after the rule's sentence."""
from datetime import datetime, timezone

from django.test import SimpleTestCase

from app.domain.user_time_zone import UnknownTimeZone, UserTimeZone


class Rule1TimeZoneIsAnIanaName(SimpleTestCase):
    """A time zone is one of the IANA names; any other name is refused."""

    def test_an_iana_name_is_accepted(self):
        self.assertEqual(UserTimeZone.parse("Asia/Jerusalem").name, "Asia/Jerusalem")
        self.assertEqual(UserTimeZone.parse("UTC").name, "UTC")

    def test_any_other_name_is_refused(self):
        for name in ["Mars/Base", "", "asia/jerusalem", "Asia/Jerusalem ", "+02:00", "../etc/passwd"]:
            with self.subTest(name=name), self.assertRaises(UnknownTimeZone):
                UserTimeZone.parse(name)

    def test_building_one_directly_is_refused_too(self):
        with self.assertRaises(UnknownTimeZone):
            UserTimeZone("Mars/Base")


class Rule2NeverChosenReadsAsUtc(SimpleTestCase):
    """A user who never chose a time zone reads times in UTC."""

    def test_empty_is_utc(self):
        self.assertEqual(UserTimeZone.of("").name, "UTC")

    def test_a_chosen_zone_is_kept(self):
        self.assertEqual(UserTimeZone.of("Asia/Jerusalem").name, "Asia/Jerusalem")


class Rule3UnknownStoredNameReadsAsUtc(SimpleTestCase):
    """A stored name that is no longer known reads as UTC (stands in for a
    name dropped from the time zone data after it was saved)."""

    def test_unknown_stored_name_is_utc(self):
        self.assertEqual(UserTimeZone.of("Gone/Zone").name, "UTC")


class Rule4ShowingAMomentNeverChangesIt(SimpleTestCase):
    """Showing a moment in a user's time zone changes how it is written,
    never the moment itself."""

    def test_same_instant_written_on_the_zones_clock(self):
        moment = datetime(2026, 12, 1, 23, 30, tzinfo=timezone.utc)
        local = UserTimeZone.parse("Asia/Jerusalem").local(moment)
        self.assertEqual(local, moment)
        self.assertEqual((local.year, local.month, local.day, local.hour, local.minute), (2026, 12, 2, 1, 30))

    def test_daylight_saving_change(self):
        london = UserTimeZone.parse("Europe/London")  # clocks go forward 2026-03-29 01:00 UTC
        before = london.local(datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc))
        after = london.local(datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc))
        self.assertEqual(before.hour, 0)
        self.assertEqual(after.hour, 2)

    def test_utc_leaves_the_clock_as_is(self):
        moment = datetime(2026, 12, 1, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(UserTimeZone.of("").local(moment).hour, 23)

    def test_a_moment_without_a_time_zone_is_refused(self):
        with self.assertRaises(ValueError):
            UserTimeZone.of("").local(datetime(2026, 12, 1, 23, 30))


class Rule6NotChosenIsAskedOnce(SimpleTestCase):
    """A user who has not chosen a time zone is asked once; answering
    either way counts as choosing."""

    def test_empty_is_not_chosen(self):
        self.assertFalse(UserTimeZone.is_chosen(""))

    def test_keep_utc_counts_as_chosen(self):
        self.assertTrue(UserTimeZone.is_chosen("UTC"))

    def test_a_zone_counts_as_chosen(self):
        self.assertTrue(UserTimeZone.is_chosen("Asia/Jerusalem"))

    def test_a_name_no_longer_known_is_asked_again(self):
        self.assertFalse(UserTimeZone.is_chosen("Gone/Zone"))
