"""Switching workspaces must land the user on the new workspace's dashboard.

The navbar switcher posts via HTMX. A plain redirect is invisible to HTMX
(fetch follows it and the body is discarded by hx-swap="none"), so the view
answers HTMX requests with an HX-Redirect header, which triggers a real
browser navigation. Reloading the page the user was on instead would 404
whenever that page belonged to the previous workspace.
"""
import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker


def _login(client, role="owner"):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role=role)
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


@pytest.mark.django_db
class TestSwitchTenant(TestCase):
    def _switch(self, tenant_id, htmx=False):
        headers = {"HX-Request": "true"} if htmx else {}
        return self.client.post(
            reverse("switch_tenant"), {"tenant_id": tenant_id}, headers=headers
        )

    def test_htmx_request_returns_hx_redirect_to_dashboard(self):
        user, _ = _login(self.client)
        other = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=other)

        response = self._switch(other.id, htmx=True)

        assert response.status_code == 200
        assert response.headers["HX-Redirect"] == reverse("dashboard")

    def test_plain_request_redirects_to_dashboard(self):
        user, _ = _login(self.client)
        other = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=other)

        response = self._switch(other.id)

        assert response.status_code == 302
        assert response.headers["Location"] == reverse("dashboard")

    def test_switch_updates_active_tenant_in_session(self):
        user, _ = _login(self.client)
        other = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=other)

        self._switch(other.id, htmx=True)

        assert self.client.session["active_tenant_id"] == str(other.id)

    def test_tenant_without_membership_leaves_session_unchanged(self):
        _, tenant = _login(self.client)
        foreign = baker.make("app.Tenant")

        response = self._switch(foreign.id, htmx=True)

        assert response.status_code == 200
        assert self.client.session["active_tenant_id"] == str(tenant.id)

    def test_unauthenticated_request_redirects_to_login(self):
        tenant = baker.make("app.Tenant")

        response = self._switch(tenant.id)

        assert response.status_code == 302
        assert response.headers["Location"].startswith(reverse("account_login"))
