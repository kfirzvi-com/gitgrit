"""A user's time zone (app.domain.user_time_zone): one test class per rule,
named after the rule's sentence."""
from datetime import datetime, timezone

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from app.domain.models import User
from app.domain.user_time_zone import UTC_NAMES, UnknownTimeZone, UserTimeZone


class Rule1TimeZoneIsAnIanaName(SimpleTestCase):
    """A time zone is one of the IANA names; any other name is refused."""

    def test_an_iana_name_is_accepted(self):
        self.assertEqual(UserTimeZone.parse("Asia/Jerusalem").name, "Asia/Jerusalem")
        self.assertEqual(UserTimeZone.parse("UTC").name, "UTC")

    def test_any_other_name_is_refused(self):
        for name in ["Mars/Base", "", "asia/jerusalem", "Asia/Jerusalem ", "+02:00", "../etc/passwd"]:
            with self.subTest(name=name), self.assertRaises(UnknownTimeZone):
                UserTimeZone.parse(name)

    def test_the_names_to_pick_from_are_the_known_ones_sorted(self):
        names = UserTimeZone.names()
        self.assertEqual(list(names), sorted(names))
        self.assertIn("Asia/Jerusalem", names)
        self.assertIn("UTC", names)
        for name in names:
            UserTimeZone.parse(name)  # every name offered is accepted

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
    """A user who has not chosen a time zone is asked once, with their
    device's zone; nothing to suggest on UTC or an unknown zone; either
    answer is a choice."""

    def test_keep_utc_counts_as_chosen(self):
        self.assertFalse(UserTimeZone.should_ask("UTC", already_asked=False))

    def test_asked_while_not_chosen_and_not_asked_before(self):
        self.assertTrue(UserTimeZone.should_ask("", already_asked=False))

    def test_asked_only_once(self):
        self.assertFalse(UserTimeZone.should_ask("", already_asked=True))

    def test_not_asked_once_chosen(self):
        self.assertFalse(UserTimeZone.should_ask("UTC", already_asked=False))

    def test_the_device_zone_is_the_suggestion(self):
        self.assertEqual(UserTimeZone.suggestion_for("Asia/Jerusalem"), UserTimeZone("Asia/Jerusalem"))

    def test_every_utc_name_is_a_known_zone(self):
        for name in UTC_NAMES:
            with self.subTest(name=name):
                UserTimeZone.parse(name)

    def test_nothing_to_suggest_on_utc_or_an_unknown_zone(self):
        for zone in ["UTC", "Etc/UTC", "Zulu", "", "Mars/Base"]:
            with self.subTest(zone=zone):
                self.assertIsNone(UserTimeZone.suggestion_for(zone))


class UserReadsItsSavedTimeZone(SimpleTestCase):
    """A user's saved ``time_zone`` is read through UserTimeZone: UTC until
    they choose, and when what they saved is no longer known."""

    def test_new_user_is_utc(self):
        self.assertEqual(User().user_time_zone, UserTimeZone.of(""))
        self.assertEqual(User().time_zone, "")

    def test_saved_zone_is_read(self):
        self.assertEqual(User(time_zone="Asia/Jerusalem").user_time_zone.name, "Asia/Jerusalem")
        self.assertEqual(User(time_zone="Gone/Zone").user_time_zone.name, "UTC")

    def test_should_be_asked_time_zone(self):
        self.assertTrue(User().should_be_asked_time_zone)
        self.assertFalse(User(time_zone="UTC").should_be_asked_time_zone)
        self.assertFalse(User(time_zone_asked_at=datetime.now(timezone.utc)).should_be_asked_time_zone)

    def test_only_a_known_name_passes_the_field_check(self):
        field = User._meta.get_field("time_zone")
        field.run_validators("Asia/Jerusalem")
        field.run_validators("")  # not chosen yet
        with self.assertRaises(ValidationError):
            field.run_validators("Mars/Base")
