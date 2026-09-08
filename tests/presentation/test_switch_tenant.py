"""Switching workspaces must land the user on the new workspace's dashboard.

The navbar switcher posts via HTMX. A plain redirect is invisible to HTMX
(fetch follows it and the body is discarded by hx-swap="none"), so the view
answers HTMX requests with an HX-Redirect header, which triggers a real
browser navigation. Reloading the page the user was on instead would 404
whenever that page belonged to the previous workspace.
"""
import logging
import uuid

import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.workspace_access import SUPPORT_VIEW_STARTED_KEY


def _login(client, role="owner", superuser=False):
    user = baker.make("app.User", is_superuser=superuser)
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
        """An ordinary user can't switch into a workspace they're not in."""
        _, tenant = _login(self.client)
        foreign = baker.make("app.Tenant")

        response = self._switch(foreign.id, htmx=True)

        assert response.status_code == 200
        assert self.client.session["active_tenant_id"] == str(tenant.id)
        assert SUPPORT_VIEW_STARTED_KEY not in self.client.session

    def test_malformed_tenant_id_is_ignored(self):
        _, tenant = _login(self.client)

        response = self._switch("not-a-uuid", htmx=True)

        assert response.status_code == 200
        assert self.client.session["active_tenant_id"] == str(tenant.id)

    def test_superuser_enters_support_view_for_foreign_workspace(self):
        """A superuser may switch into any workspace; that is the support
        view, timestamped in the session and logged."""
        _login(self.client, superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")

        with self.assertLogs("app.support_view", level=logging.WARNING) as logs:
            response = self._switch(foreign.id, htmx=True)

        assert response.status_code == 200
        assert response.headers["HX-Redirect"] == reverse("dashboard")
        assert self.client.session["active_tenant_id"] == str(foreign.id)
        assert SUPPORT_VIEW_STARTED_KEY in self.client.session
        assert "room-one" in "\n".join(logs.output)

        page = self.client.get(reverse("dashboard"))
        assert page.wsgi_request.tenant == foreign
        assert page.wsgi_request.tenant_is_support_view is True

    def test_superuser_switching_to_unknown_workspace_stays_put(self):
        _, tenant = _login(self.client, superuser=True)

        self._switch(uuid.uuid4(), htmx=True)

        assert self.client.session["active_tenant_id"] == str(tenant.id)
        assert SUPPORT_VIEW_STARTED_KEY not in self.client.session

    def test_superuser_switching_back_to_own_workspace_ends_support_view(self):
        user, home = _login(self.client, superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        self._switch(foreign.id, htmx=True)
        assert SUPPORT_VIEW_STARTED_KEY in self.client.session

        self._switch(home.id, htmx=True)

        assert self.client.session["active_tenant_id"] == str(home.id)
        assert SUPPORT_VIEW_STARTED_KEY not in self.client.session

    def test_unauthenticated_request_redirects_to_login(self):
        tenant = baker.make("app.Tenant")

        response = self._switch(tenant.id)

        assert response.status_code == 302
        assert response.headers["Location"].startswith(reverse("account_login"))


@pytest.mark.django_db
class TestLeaveSupportView(TestCase):
    def test_back_to_my_workspace_drops_support_view(self):
        _, home = _login(self.client, superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        self.client.post(reverse("switch_tenant"), {"tenant_id": foreign.id})

        response = self.client.post(reverse("leave_support_view"))

        assert response.status_code == 302
        assert response.headers["Location"] == reverse("dashboard")
        assert SUPPORT_VIEW_STARTED_KEY not in self.client.session
        page = self.client.get(reverse("dashboard"))
        assert page.wsgi_request.tenant == home
        assert page.wsgi_request.tenant_is_support_view is False

    def test_leaving_when_not_in_support_view_is_a_noop(self):
        _, home = _login(self.client)

        response = self.client.post(reverse("leave_support_view"))

        assert response.status_code == 302
        assert self.client.session["active_tenant_id"] == str(home.id)

    def test_get_is_not_allowed(self):
        _login(self.client, superuser=True)

        response = self.client.get(reverse("leave_support_view"))

        assert response.status_code == 405

