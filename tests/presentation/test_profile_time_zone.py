"""Choosing your time zone: the Profile picker, the question asked once
(rule 6), and rule 5: only the user sets their own time zone."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.admin import UserAdmin
from app.domain.models import Notification
from app.domain.models import Membership
from app.domain.notifications import Kind
from app.domain.notifications.inbox import Inbox
from app.domain.notifications.notification_routing import route_for
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


class AskedOnce(TestCase):
    """Rule 6: a user who has not chosen a time zone is asked once, with their
    device's zone; a note in their notification center keeps the question;
    either answer is a choice; ignoring it is not asked again."""

    PLACEHOLDER = 'id="time-zone-question"'

    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="member")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def ask(self, device_zone="Asia/Jerusalem"):
        return self.client.post(reverse("time_zone_question"), {"device_time_zone": device_zone}, HTTP_HX_REQUEST="true")

    def test_pages_carry_the_question_while_not_asked(self):
        self.assertContains(self.client.get(reverse("dashboard")), self.PLACEHOLDER)

    def test_the_question_suggests_the_device_zone_with_both_answers(self):
        html = self.ask().content.decode()
        self.assertIn("Your device is in <strong>Asia/Jerusalem</strong>", html)
        self.assertIn('name="time_zone" value="Asia/Jerusalem"', html)
        self.assertIn('name="time_zone" value="UTC"', html)

    def test_asked_once_even_if_ignored(self):
        self.ask()
        self.assertEqual(self.ask().content, b"")
        self.assertNotContains(self.client.get(reverse("dashboard")), self.PLACEHOLDER)

    def test_asking_puts_one_note_in_every_workspace_of_the_user(self):
        other = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=other, role="owner")
        with self.captureOnCommitCallbacks(execute=True):
            self.ask()
            self.ask()
        notes = Notification.objects.filter(kind=Kind.TIME_ZONE_NOT_CHOSEN)
        self.assertEqual({n.tenant_id for n in notes}, {self.tenant.id, other.id})
        self.assertEqual(notes.count(), 2)
        for note in notes:
            self.assertEqual(route_for(note.kind).recipients(note), [str(self.user.pk)])

    def test_choosing_reads_the_note_everywhere(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.ask()
        note = Notification.objects.get(kind=Kind.TIME_ZONE_NOT_CHOSEN)
        Inbox(self.user.pk, self.tenant.pk).receive(note)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("update_time_zone"), {"time_zone": "Asia/Jerusalem"}, HTTP_HX_REQUEST="true")
        self.assertEqual(Inbox(self.user.pk, self.tenant.pk).unread_count(), 0)

    def test_no_workspace_means_no_note(self):
        Membership.objects.filter(user=self.user).delete()
        with self.captureOnCommitCallbacks(execute=True):
            self.ask()
        self.assertFalse(Notification.objects.exists())

    def test_a_device_on_utc_has_nothing_to_ask(self):
        self.assertEqual(self.ask("Etc/UTC").content, b"")
        self.assertFalse(Notification.objects.exists())
        self.assertNotContains(self.client.get(reverse("dashboard")), self.PLACEHOLDER)

    def test_keep_utc_saves_utc_in_place(self):
        r = self.client.post(reverse("update_time_zone"), {"time_zone": "UTC"}, HTTP_HX_REQUEST="true")
        self.assertEqual((r.status_code, r.content), (200, b""))
        self.assertIn("Time zone set to UTC.", r["HX-Trigger"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.time_zone, "UTC")

    def test_in_place_save_leaves_no_message_for_the_next_page(self):
        self.client.post(reverse("update_time_zone"), {"time_zone": "UTC"}, HTTP_HX_REQUEST="true")
        self.assertNotContains(self.client.get(reverse("profile")), "Time zone set to")

    def test_an_error_keeps_the_question(self):
        r = self.client.post(reverse("update_time_zone"), {"time_zone": "Mars/Base"}, HTTP_HX_REQUEST="true")
        self.assertIn("Pick a time zone from the list.", r["HX-Trigger"])
        self.assertEqual(r["HX-Reswap"], "none")
        self.user.refresh_from_db()
        self.assertEqual(self.user.time_zone, "")

    def test_not_on_the_profile_page(self):
        self.assertNotContains(self.client.get(reverse("profile")), self.PLACEHOLDER)

    def test_not_when_signed_out(self):
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("account_login")), self.PLACEHOLDER)


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
