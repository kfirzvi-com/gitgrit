"""After connecting a git platform, the admin goes where the next step is.

A new connection has nothing in it yet, so it leads straight on to picking its
repositories; refreshing one already held goes back to the connections list
rather than to whichever settings section happens to open first."""
from __future__ import annotations

from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from app.domain.models import (
    AuthMethod,
    Membership,
    Platform,
    PlatformConnection,
    Tenant,
    User,
)

INSTALLATION = {"id": 7001, "account_login": "acme-corp", "account_type": "Organization"}
CONNECTIONS = reverse("tenant_settings") + "#section-connections"


@override_settings(
    GITHUB_APP_ENABLED=True,
    GITHUB_APP_SLUG="gitgrit",
    GITHUB_APP_CLIENT_ID="Iv23test",
    GITHUB_APP_CLIENT_SECRET="secret",
)
class ConnectGoesToRepositoriesTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        self.user = User.objects.create_user(
            username="admin", email="admin@example.com", password="pw"
        )
        Membership.objects.create(
            user=self.user, tenant=self.tenant, role=Membership.Role.OWNER
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def _choose(self):
        with mock.patch(
            "app.infrastructure.github_app.exchange_user_code", return_value="user-token"
        ), mock.patch(
            "app.infrastructure.github_app.list_user_installations",
            return_value=[INSTALLATION],
        ):
            self.client.get(reverse("github_app_callback"), {"code": "oauth-code"})
            return self.client.post(
                reverse("github_app_choose"), {"installation_id": str(INSTALLATION["id"])}
            )

    def test_a_new_app_connection_leads_to_picking_its_repositories(self):
        response = self._choose()

        connection = PlatformConnection.objects.get(tenant=self.tenant)
        self.assertRedirects(
            response,
            reverse("add_project_search", args=[connection.id]),
            fetch_redirect_response=False,
        )

    def test_reconnecting_an_app_connection_goes_back_to_the_connections(self):
        PlatformConnection.objects.create(
            tenant=self.tenant,
            platform=Platform.GITHUB,
            display_name="GitHub App (acme-corp)",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=INSTALLATION["id"],
            account_login="acme-corp",
        )

        response = self._choose()

        self.assertRedirects(response, CONNECTIONS, fetch_redirect_response=False)

    def test_a_new_token_connection_leads_to_picking_its_repositories(self):
        response = self.client.post(
            reverse("add_connection"),
            {"platform": "github", "access_token": "test-token", "display_name": ""},
        )

        connection = PlatformConnection.objects.get(tenant=self.tenant)
        self.assertRedirects(
            response,
            reverse("add_project_search", args=[connection.id]),
            fetch_redirect_response=False,
        )
