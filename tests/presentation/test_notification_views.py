"""View tests for the Notifications page, the open redirect and mark-all-read."""
from datetime import timedelta

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.domain.models import Notification, NotificationDelivery

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

EMPTY_ACTIVE = "Nothing needs your attention."
EMPTY_HISTORY = "No read notifications yet."


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestNotificationViews(TestCase):
    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="member")
        self.client.force_login(self.user)
        self._activate(self.tenant)

    def _activate(self, tenant):
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()

    def _delivery(self, title="Something", user=None, tenant=None, channel="inbox",
                  read_at=None, url="/dashboard/"):
        notification = baker.make(
            "app.Notification",
            tenant=tenant or self.tenant,
            title=title,
            severity="warning",
            kind="test.kind",
            url=url,
        )
        return baker.make(
            "app.NotificationDelivery",
            notification=notification,
            recipient=user or self.user,
            channel=channel,
            status="sent",
            read_at=read_at,
        )

    def test_list_scopes_to_user_workspace_and_inbox(self):
        self._delivery("mine")
        self._delivery("theirs", user=baker.make("app.User"))
        self._delivery("elsewhere", tenant=baker.make("app.Tenant"))
        self._delivery("logged", channel="log")

        response = self.client.get(reverse("notification_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mine")
        for hidden in ("theirs", "elsewhere", "logged"):
            self.assertNotContains(response, hidden)

    def test_unread_under_active_and_read_under_history(self):
        self._delivery("unread-item")
        self._delivery("read-item", read_at=timezone.now())

        response = self.client.get(reverse("notification_list"))

        self.assertContains(response, "Active")
        self.assertContains(response, "History")
        self.assertEqual([d.notification.title for d in response.context["active"]], ["unread-item"])
        self.assertEqual([d.notification.title for d in response.context["history"]], ["read-item"])
        self.assertContains(response, "Mark all read")

    def _created(self, delivery, when):
        # auto_now_add ignores the value passed to create, so set it afterwards.
        Notification.objects.filter(pk=delivery.notification_id).update(created_at=when)

    def test_active_is_grouped_by_day(self):
        now = timezone.now()
        self._created(self._delivery("today-item"), now)
        self._created(self._delivery("yesterday-item"), now - timedelta(days=1))
        self._created(self._delivery("older-item"), now - timedelta(days=3))

        response = self.client.get(reverse("notification_list"))

        groups = [
            (label, [d.notification.title for d in items])
            for label, items in response.context["active_groups"]
        ]
        self.assertEqual(
            groups,
            [("Today", ["today-item"]), ("Yesterday", ["yesterday-item"]), ("Older", ["older-item"])],
        )
        self.assertContains(response, 'data-time-format="time"', count=1)
        self.assertContains(response, 'data-day-group="Yesterday"')

    def test_active_groups_leave_out_empty_days(self):
        self._created(self._delivery("older-item"), timezone.now() - timedelta(days=3))

        response = self.client.get(reverse("notification_list"))

        self.assertEqual([label for label, _ in response.context["active_groups"]], ["Older"])

    def test_history_shows_more_button_only_past_five(self):
        for i in range(5):
            self._delivery(f"read-{i}", read_at=timezone.now())
        self.assertNotContains(self.client.get(reverse("notification_list")), "Show more")

        for i in range(5, 7):
            self._delivery(f"read-{i}", read_at=timezone.now())
        response = self.client.get(reverse("notification_list"))

        self.assertContains(response, "Show more")
        self.assertContains(response, "<div data-history-row", count=7)
        self.assertContains(response, 'last:border-b-0 hidden"', count=2)

    def test_empty_state(self):
        response = self.client.get(reverse("notification_list"))

        self.assertContains(response, EMPTY_ACTIVE)
        self.assertContains(response, EMPTY_HISTORY)
        self.assertNotContains(response, "Mark all read")

    def test_open_marks_read_and_redirects(self):
        delivery = self._delivery(url="/standards/")
        url = reverse("notification_open", args=[delivery.pk])

        response = self.client.get(url)

        self.assertRedirects(response, "/standards/", fetch_redirect_response=False)
        delivery.refresh_from_db()
        first_read = delivery.read_at
        self.assertIsNotNone(first_read)

        self.assertEqual(self.client.get(url).status_code, 302)
        delivery.refresh_from_db()
        self.assertEqual(delivery.read_at, first_read)

    def test_open_without_url_falls_back_to_list(self):
        delivery = self._delivery(url="")
        response = self.client.get(reverse("notification_open", args=[delivery.pk]))
        self.assertRedirects(response, reverse("notification_list"), fetch_redirect_response=False)

    def test_open_never_redirects_off_site(self):
        delivery = self._delivery(url="https://example.com/")
        response = self.client.get(reverse("notification_open", args=[delivery.pk]))
        self.assertRedirects(response, reverse("notification_list"), fetch_redirect_response=False)
        delivery.refresh_from_db()
        self.assertIsNotNone(delivery.read_at)

    def test_open_other_users_delivery_is_404(self):
        delivery = self._delivery(user=baker.make("app.User"))
        response = self.client.get(reverse("notification_open", args=[delivery.pk]))
        self.assertEqual(response.status_code, 404)
        delivery.refresh_from_db()
        self.assertIsNone(delivery.read_at)

    def test_mark_all_read_only_touches_my_unread_in_this_workspace(self):
        mine = self._delivery("a")
        mine2 = self._delivery("b")
        other_user = self._delivery("c", user=baker.make("app.User"))
        other_tenant = self._delivery("d", tenant=baker.make("app.Tenant"))

        response = self.client.post(reverse("notifications_mark_all_read"))

        self.assertRedirects(response, reverse("notification_list"))
        for d in (mine, mine2):
            d.refresh_from_db()
            self.assertIsNotNone(d.read_at)
        for d in (other_user, other_tenant):
            d.refresh_from_db()
            self.assertIsNone(d.read_at)

    def test_pin_keeps_the_item_unread_when_opened(self):
        delivery = self._delivery(url="/standards/")

        response = self.client.post(reverse("notification_pin", args=[delivery.pk]))

        self.assertRedirects(response, reverse("notification_list"))
        delivery.refresh_from_db()
        self.assertIsNotNone(delivery.pinned_at)
        self.client.get(reverse("notification_open", args=[delivery.pk]))
        delivery.refresh_from_db()
        self.assertIsNone(delivery.read_at)

    def test_mark_all_read_skips_pinned(self):
        pinned = self._delivery("pinned")
        plain = self._delivery("plain")
        self.client.post(reverse("notification_pin", args=[pinned.pk]))

        self.client.post(reverse("notifications_mark_all_read"))

        pinned.refresh_from_db()
        plain.refresh_from_db()
        self.assertIsNone(pinned.read_at)
        self.assertIsNotNone(plain.read_at)

    def test_unpin_lets_open_mark_it_read_again(self):
        delivery = self._delivery()
        self.client.post(reverse("notification_pin", args=[delivery.pk]))
        self.client.post(reverse("notification_pin", args=[delivery.pk]))

        delivery.refresh_from_db()
        self.assertIsNone(delivery.pinned_at)
        self.client.get(reverse("notification_open", args=[delivery.pk]))
        delivery.refresh_from_db()
        self.assertIsNotNone(delivery.read_at)

    def test_pinning_a_read_item_brings_it_back_to_active(self):
        delivery = self._delivery("was-read", read_at=timezone.now())

        self.client.post(reverse("notification_pin", args=[delivery.pk]))

        response = self.client.get(reverse("notification_list"))
        self.assertEqual([d.notification.title for d in response.context["active"]], ["was-read"])
        self.assertEqual(list(response.context["history"]), [])

    def test_pinned_items_come_first_in_active(self):
        older = self._delivery("older")
        self._delivery("newer")
        self.client.post(reverse("notification_pin", args=[older.pk]))

        response = self.client.get(reverse("notification_list"))

        self.assertEqual(
            [d.notification.title for d in response.context["active"]], ["older", "newer"]
        )
        self.assertContains(response, "Unpin")

    def test_pin_other_users_delivery_is_404(self):
        delivery = self._delivery(user=baker.make("app.User"))
        response = self.client.post(reverse("notification_pin", args=[delivery.pk]))
        self.assertEqual(response.status_code, 404)

    def test_pin_requires_post(self):
        delivery = self._delivery()
        self.assertEqual(self.client.get(reverse("notification_pin", args=[delivery.pk])).status_code, 405)

    def test_mark_all_read_requires_post(self):
        self.assertEqual(self.client.get(reverse("notifications_mark_all_read")).status_code, 405)

    def test_user_without_workspace_sees_empty_state(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        response = self.client.get(reverse("notification_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, EMPTY_ACTIVE)
        self.assertContains(response, EMPTY_HISTORY)
        self.assertEqual(NotificationDelivery.objects.filter(recipient=user).count(), 0)


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestNotificationPollPartials(TestCase):
    """The Active card and the navbar bell re-fetch themselves by HTMX poll."""

    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="member")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def _unread(self, title, tenant=None):
        notification = baker.make(
            "app.Notification", tenant=tenant or self.tenant, title=title,
            severity="warning", kind="test.kind", url="/dashboard/",
        )
        return baker.make(
            "app.NotificationDelivery", notification=notification,
            recipient=self.user, channel="inbox", status="sent", read_at=None,
        )

    def test_page_polls_the_active_card_and_the_bell(self):
        response = self.client.get(reverse("notification_list"))

        content = response.content.decode()
        self.assertIn(f'hx-get="{reverse("notification_active")}"', content)
        self.assertIn(f'hx-get="{reverse("notification_bell")}"', content)
        self.assertEqual(content.count("every 30s [document.visibilityState=='visible']"), 2)

    def test_active_partial_is_the_card_alone_scoped_to_the_workspace(self):
        self._unread("mine")
        self._unread("elsewhere", tenant=baker.make("app.Tenant"))

        response = self.client.get(reverse("notification_active"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("mine", content)
        self.assertNotIn("elsewhere", content)
        self.assertNotIn("<html", content)
        self.assertNotIn("History", content)
        self.assertIn("data-active-section", content)

    def test_active_partial_shows_the_empty_state(self):
        response = self.client.get(reverse("notification_active"))

        self.assertContains(response, EMPTY_ACTIVE)

    def test_bell_partial_carries_the_unread_count(self):
        self._unread("one")
        self._unread("two")

        response = self.client.get(reverse("notification_bell"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('aria-label="Notifications"', content)
        self.assertIn('badge badge-error badge-sm">2<', content)
        self.assertNotIn("<html", content)

    def test_partials_require_login(self):
        self.client.logout()
        for name in ("notification_active", "notification_bell"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
