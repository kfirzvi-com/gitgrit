"""The GitHub App install callback view.

A valid callback (with a state signed for this user+tenant) confirms the
installation and records a tenant-scoped App connection. A tampered or foreign
state is rejected and creates nothing.
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


@pytest.mark.django_db
@override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_SLUG="gitgrit-app")
class TestGitHubAppCallback(TestCase):
    def test_valid_callback_creates_app_connection(self):
        user, tenant = _login(self.client)
        state = _state(tenant.id, user.id)
        with mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ) as mock_get:
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": "9001", "setup_action": "install", "state": state},
            )
        assert resp.status_code == 302
        mock_get.assert_called_once_with(9001)

        conn = PlatformConnection.objects.get(tenant=tenant, installation_id=9001)
        assert conn.auth_method == AuthMethod.GITHUB_APP
        assert conn.account_login == "acme"
        assert conn.account_type == "Organization"

    def test_tampered_state_is_rejected(self):
        user, tenant = _login(self.client)
        with mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ) as mock_get:
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": "9001", "state": _state(tenant.id, user.id) + "x"},
            )
        assert resp.status_code == 302
        mock_get.assert_not_called()
        assert not PlatformConnection.objects.filter(installation_id=9001).exists()

    def test_foreign_state_for_other_tenant_is_rejected(self):
        user, tenant = _login(self.client)
        other_tenant = baker.make("app.Tenant")
        # State signed for a different tenant than the logged-in one.
        state = _state(other_tenant.id, user.id)
        with mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ) as mock_get:
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": "9001", "state": state},
            )
        assert resp.status_code == 302
        mock_get.assert_not_called()
        assert not PlatformConnection.objects.filter(installation_id=9001).exists()
