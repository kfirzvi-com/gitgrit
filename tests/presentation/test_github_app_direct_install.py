"""Installing the App straight from github.com, and re-entering an existing one.

Someone who installs from the App's own page arrives with no install ``state``:
nothing tied that visit to a workspace. Rather than stranding them, confirm the
target workspace explicitly, then connect.

Any number of workspaces may connect the same installation — each is an
independent grant by someone GitHub says has access — so nothing here may
reveal that another workspace holds it.
"""
from unittest import mock

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AuthMethod, PlatformConnection
from tests.support import administers_account

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

APP_SETTINGS = dict(
    GITHUB_APP_ENABLED=True,
    GITHUB_APP_SLUG="gitgrit-app",
    GITHUB_APP_CLIENT_ID="Iv1.client",
    GITHUB_APP_CLIENT_SECRET="shhh",
    STORAGES=NON_MANIFEST_STORAGES,
)

INSTALLATION_ID = 9001
_INSTALLATION = {
    "id": INSTALLATION_ID,
    "account": {"login": "acme", "type": "Organization"},
}


def _login(client, role="owner", tenant_name="Workspace"):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant", name=tenant_name)
    baker.make("app.Membership", user=user, tenant=tenant, role=role)
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


def _entitled(allowed=True):
    return (
        mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="ghu_usertoken",
        ),
        mock.patch(
            "app.infrastructure.github_app.user_can_access_installation",
            return_value=allowed,
        ),
        mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ),
        administers_account(),
    )


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestDirectInstall(TestCase):
    def test_stateless_callback_asks_before_connecting(self):
        _login(self.client, tenant_name="Acme HQ")
        exchange, access, get_inst, reach = _entitled()
        with exchange, access, get_inst, reach:
            resp = self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(INSTALLATION_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                },
            )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "acme" in body
        assert "Acme HQ" in body
        # Nothing is connected until the user confirms.
        assert not PlatformConnection.objects.exists()

    def test_confirming_creates_the_connection(self):
        _, tenant = _login(self.client)
        exchange, access, get_inst, reach = _entitled()
        with exchange, access, get_inst, reach:
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(INSTALLATION_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                },
            )
        resp = self.client.post(reverse("github_app_confirm"))
        assert resp.status_code == 302

        conn = PlatformConnection.objects.get(tenant=tenant)
        assert conn.installation_id == INSTALLATION_ID
        assert conn.auth_method == AuthMethod.GITHUB_APP
        assert conn.account_login == "acme"

    def test_confirm_without_a_verified_installation_is_rejected(self):
        """The POST trusts only what the verified GET put in the session."""
        _login(self.client)
        resp = self.client.post(reverse("github_app_confirm"))
        assert resp.status_code == 302
        assert not PlatformConnection.objects.exists()

    def test_two_workspaces_may_connect_the_same_installation(self):
        _, tenant_a = _login(self.client, tenant_name="Alpha")
        exchange, access, get_inst, reach = _entitled()
        with exchange, access, get_inst, reach:
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(INSTALLATION_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                },
            )
            self.client.post(reverse("github_app_confirm"))

        # A different user, in a different workspace, equally entitled.
        other_client = self.client_class()
        _, tenant_b = _login(other_client, tenant_name="Beta")
        exchange, access, get_inst, reach = _entitled()
        with exchange, access, get_inst, reach:
            resp = other_client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(INSTALLATION_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                },
            )
            body = resp.content.decode()
            other_client.post(reverse("github_app_confirm"))

        assert PlatformConnection.objects.filter(
            tenant=tenant_a, installation_id=INSTALLATION_ID
        ).exists()
        assert PlatformConnection.objects.filter(
            tenant=tenant_b, installation_id=INSTALLATION_ID
        ).exists()
        # Beta must learn nothing about Alpha.
        assert "Alpha" not in body

    def test_update_without_a_code_refreshes_an_existing_connection(self):
        """Reconfiguring an install returns via setup_on_update with no code.

        No new access is being granted — the workspace already holds this
        installation — so refresh it instead of failing the entitlement check.
        """
        _, tenant = _login(self.client)
        baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=INSTALLATION_ID,
            account_login="stale",
            display_name="GitHub App (stale)",
        )
        with mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ):
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": str(INSTALLATION_ID), "setup_action": "update"},
            )
        assert resp.status_code == 302
        conn = PlatformConnection.objects.get(tenant=tenant)
        assert conn.account_login == "acme"

    def test_update_without_a_code_or_existing_connection_connects_nothing(self):
        _login(self.client)
        with mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ) as mock_get:
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": str(INSTALLATION_ID), "setup_action": "update"},
            )
        assert resp.status_code == 302
        mock_get.assert_not_called()
        assert not PlatformConnection.objects.exists()

    def test_install_request_is_reported_not_errored(self):
        """A member asking an org owner to approve the install has no id yet."""
        _login(self.client)
        resp = self.client.get(
            reverse("github_app_callback"), {"setup_action": "request"}
        )
        assert resp.status_code == 302
        assert not PlatformConnection.objects.exists()
