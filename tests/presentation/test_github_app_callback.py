"""The GitHub App install callback view.

A callback is accepted only when GitHub itself confirms the signed-in user may
access the installation (the user-to-server OAuth check). The install ``state``
targets a tenant+user and is rejected when tampered, foreign, or stale — but it
is never treated as proof of entitlement; see
``test_github_app_install_entitlement``.
"""
from unittest import mock

import pytest
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AuthMethod, PlatformConnection
from app.presentation.views.github_app_views import INSTALL_STATE_SALT

_INSTALLATION = {
    "id": 9001,
    "account": {"login": "acme", "type": "Organization"},
}

APP_SETTINGS = dict(
    GITHUB_APP_ENABLED=True,
    GITHUB_APP_SLUG="gitgrit-app",
    GITHUB_APP_CLIENT_ID="Iv1.client",
    GITHUB_APP_CLIENT_SECRET="shhh",
)


def _login(client, role="owner"):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role=role)
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


def _state(tenant_id, user_id, nonce="n1"):
    return signing.dumps(
        {"tenant_id": str(tenant_id), "user_id": str(user_id), "nonce": nonce},
        salt=INSTALL_STATE_SALT,
    )


def _entitled(allowed=True):
    """Patch the two GitHub round-trips the entitlement check performs."""
    return (
        mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="ghu_usertoken",
        ),
        mock.patch(
            "app.infrastructure.github_app.user_can_access_installation",
            return_value=allowed,
        ),
    )


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestGitHubAppCallback(TestCase):
    def test_valid_callback_creates_app_connection(self):
        user, tenant = _login(self.client)
        exchange, can_access = _entitled()
        with exchange as mock_exchange, can_access as mock_access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ) as mock_get:
            resp = self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": "9001",
                    "setup_action": "install",
                    "code": "oauth-code",
                    "state": _state(tenant.id, user.id),
                },
            )
        assert resp.status_code == 302
        mock_exchange.assert_called_once_with("oauth-code")
        mock_access.assert_called_once_with("ghu_usertoken", 9001)
        mock_get.assert_called_once_with(9001)

        conn = PlatformConnection.objects.get(tenant=tenant, installation_id=9001)
        assert conn.auth_method == AuthMethod.GITHUB_APP
        assert conn.account_login == "acme"
        assert conn.account_type == "Organization"

    def test_tampered_state_is_rejected(self):
        user, tenant = _login(self.client)
        exchange, can_access = _entitled()
        with exchange, can_access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ) as mock_get:
            resp = self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": "9001",
                    "code": "oauth-code",
                    "state": _state(tenant.id, user.id) + "x",
                },
            )
        assert resp.status_code == 302
        mock_get.assert_not_called()
        assert not PlatformConnection.objects.filter(installation_id=9001).exists()

    def test_foreign_state_for_other_tenant_is_rejected(self):
        user, _tenant = _login(self.client)
        other_tenant = baker.make("app.Tenant")
        exchange, can_access = _entitled()
        with exchange, can_access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ) as mock_get:
            resp = self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": "9001",
                    "code": "oauth-code",
                    "state": _state(other_tenant.id, user.id),
                },
            )
        assert resp.status_code == 302
        mock_get.assert_not_called()
        assert not PlatformConnection.objects.filter(installation_id=9001).exists()

    def test_stale_state_is_rejected(self):
        """A state is a short-lived targeting token, not a durable credential."""
        user, tenant = _login(self.client)
        exchange, can_access = _entitled()
        with exchange, can_access, mock.patch(
            "django.core.signing.loads", side_effect=signing.SignatureExpired("old")
        ), mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ) as mock_get:
            resp = self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": "9001",
                    "code": "oauth-code",
                    "state": _state(tenant.id, user.id),
                },
            )
        assert resp.status_code == 302
        mock_get.assert_not_called()
        assert not PlatformConnection.objects.filter(installation_id=9001).exists()
