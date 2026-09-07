"""Members can leave a workspace; the last owner cannot.

Leaving deletes the user's own membership and clears the active workspace so
the middleware picks another one. A sole owner is refused, otherwise the
workspace would have nobody able to manage it.
"""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _login(client, role="owner"):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant", name="Home", slug="home")
    baker.make("app.Membership", user=user, tenant=tenant, role=role)
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestLeaveWorkspace(TestCase):
    url = reverse("leave_workspace")

    def test_member_can_leave(self):
        user, tenant = _login(self.client, role="member")
        baker.make("app.Membership", tenant=tenant, role="owner")
        home = baker.make("app.Tenant", name="Other")
        baker.make("app.Membership", user=user, tenant=home)

        response = self.client.post(self.url)

        assert response.status_code == 302
        assert response.headers["Location"] == reverse("dashboard")
        assert not user.memberships.filter(tenant=tenant).exists()
        # Middleware picks the remaining workspace on the next request.
        self.client.get(reverse("dashboard"))
        assert self.client.session["active_tenant_id"] == str(home.id)

    def test_sole_owner_cannot_leave(self):
        user, tenant = _login(self.client, role="owner")

        response = self.client.post(self.url, follow=True)

        assert user.memberships.filter(tenant=tenant).exists()
        assert "only owner" in response.content.decode()

    def test_owner_can_leave_when_another_owner_exists(self):
        user, tenant = _login(self.client, role="owner")
        baker.make("app.Membership", tenant=tenant, role="owner")

        self.client.post(self.url)

        assert not user.memberships.filter(tenant=tenant).exists()

    def test_get_is_rejected(self):
        _login(self.client)

        assert self.client.post(self.url).status_code == 302
        assert self.client.get(self.url).status_code == 405

    def test_settings_page_shows_leave_button_or_explanation(self):
        user, tenant = _login(self.client, role="owner")

        html = self.client.get(reverse("tenant_settings")).content.decode()
        assert "only owner" in html
        assert 'action="%s"' % self.url not in html

        baker.make("app.Membership", tenant=tenant, role="owner")
        html = self.client.get(reverse("tenant_settings")).content.decode()
        assert 'action="%s"' % self.url in html
