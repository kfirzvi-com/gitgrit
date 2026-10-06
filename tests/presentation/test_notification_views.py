"""View tests for the Notifications page, the open redirect and mark-all-read."""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.domain.models import NotificationDelivery

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
