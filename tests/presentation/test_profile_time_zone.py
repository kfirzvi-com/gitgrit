"""Picking your time zone on the Profile page (rule 5: only the user sets
their own time zone)."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.admin import UserAdmin
from app.presentation.api.views import MeView


class ProfileTimeZoneTests(TestCase):
    def setUp(self):
        self.user = baker.make("app.User", email="dev@example.com")
        self.client.force_login(self.user)

    def test_picked_zone_is_saved_and_shown_selected(self):
        r = self.client.post(reverse("update_time_zone"), {"time_zone": "Asia/Jerusalem"}, follow=True)
        self.user.refresh_from_db()
        self.assertEqual(self.user.time_zone, "Asia/Jerusalem")
        self.assertContains(r, "Time zone set to Asia/Jerusalem.")
        page = self.client.get(reverse("profile"))
        self.assertContains(page, '<option value="Asia/Jerusalem" selected>')

    def test_never_chosen_shows_utc_selected(self):
        page = self.client.get(reverse("profile"))
        self.assertContains(page, '<option value="UTC" selected>')

    def test_unknown_name_is_refused_and_nothing_saved(self):
        self.user.time_zone = "Europe/London"
        self.user.save()
        r = self.client.post(reverse("update_time_zone"), {"time_zone": "Mars/Base"}, follow=True)
        self.user.refresh_from_db()
        self.assertEqual(self.user.time_zone, "Europe/London")
        self.assertContains(r, "Pick a time zone from the list.")

    def test_missing_name_is_refused(self):
        self.client.post(reverse("update_time_zone"), {})
        self.user.refresh_from_db()
        self.assertEqual(self.user.time_zone, "")


class OnlyTheUserSetsTheirOwnTimeZone(TestCase):
    """Rule 5: only the user sets their own time zone."""

    def test_it_changes_only_the_signed_in_user(self):
        me, other = baker.make("app.User"), baker.make("app.User")
        self.client.force_login(me)
        self.client.post(reverse("update_time_zone"), {"time_zone": "Asia/Jerusalem"})
        me.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((me.time_zone, other.time_zone), ("Asia/Jerusalem", ""))

    def test_signed_out_is_sent_to_login_and_nothing_saved(self):
        user = baker.make("app.User")
        r = self.client.post(reverse("update_time_zone"), {"time_zone": "Asia/Jerusalem"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("account_login"), r["Location"])
        user.refresh_from_db()
        self.assertEqual(user.time_zone, "")

    def test_the_api_cannot_change_it(self):
        self.assertFalse(any(hasattr(MeView, m) for m in ("put", "patch", "post")))

    def test_the_admin_does_not_show_it(self):
        fields = {f for _, opts in UserAdmin.fieldsets for f in opts["fields"]}
        self.assertNotIn("time_zone", fields)
