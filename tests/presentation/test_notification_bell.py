"""The navbar bell: unread count scoped to the active workspace."""
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.context_processors import notification_context

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
BADGE = "indicator-item badge badge-error"
BELL = 'aria-label="Notifications"'


def _inbox(user, tenant, **kw):
    notification = baker.make("app.Notification", tenant=tenant)
    return baker.make(
        "app.NotificationDelivery",
        notification=notification,
        recipient=user,
        channel="inbox",
        status="sent",
        read_at=None,
        **kw,
    )


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestNotificationBell(TestCase):
    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        self.other = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="admin")
        baker.make("app.Membership", user=self.user, tenant=self.other, role="admin")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def test_badge_counts_unread_in_active_workspace_only(self):
        _inbox(self.user, self.tenant)
        _inbox(self.user, self.tenant)
        _inbox(self.user, self.other)
        body = self.client.get(reverse("dashboard")).content.decode()
        assert BELL in body
        assert f'{BADGE} badge-sm">2</span>' in body

    def test_no_badge_when_nothing_unread(self):
        body = self.client.get(reverse("dashboard")).content.decode()
        assert BELL in body
        assert BADGE not in body

    def test_anonymous_sees_no_bell(self):
        self.client.logout()
        body = self.client.get(reverse("account_login")).content.decode()
        assert BELL not in body

    def test_context_processor_empty_without_tenant(self):
        request = RequestFactory().get("/")
        request.user = self.user
        request.tenant = None
        assert notification_context(request) == {}
        request.user = AnonymousUser()
        assert notification_context(request) == {}
