"""Entitlement: a workspace may only connect installations its user can access.

The signed install ``state`` proves *who* started the flow, but it says nothing
about *which* installation comes back — GitHub returns ``installation_id`` as a
plain query parameter. Without an entitlement check, any admin of any workspace
can mint a state for themselves and replay it with someone else's installation
id, gaining read access to that org's private repositories.
"""
from unittest import mock

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import PlatformConnection
from tests.support import administers_account

VICTIM_INSTALLATION_ID = 5201

_VICTIM_INSTALLATION = {
    "id": VICTIM_INSTALLATION_ID,
    "account": {"login": "victim-org", "type": "Organization"},
}


APP_SETTINGS = dict(
    GITHUB_APP_ENABLED=True,
    GITHUB_APP_SLUG="gitgrit-app",
    GITHUB_APP_CLIENT_ID="Iv1.client",
    GITHUB_APP_CLIENT_SECRET="shhh",
)


def _login_owner(client):
    """An ordinary user who owns their own (attacker-controlled) workspace."""
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestInstallationEntitlement(TestCase):
    def test_self_issued_state_cannot_claim_a_foreign_installation(self):
        """The full exploit, using only the app's own endpoints.

        The attacker never talks to GitHub: they read a valid state straight out
        of the install redirect, then hand it back with a victim's installation
        id attached.
        """
        _, attacker_tenant = _login_owner(self.client)

        # 1. Mint a state by simply following our own install endpoint.
        resp = self.client.get(reverse("github_app_install"))
        assert resp.status_code == 302
        state = resp.headers["Location"].split("state=")[1]

        # 2. Replay it with an installation id the attacker does not own.
        with mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_VICTIM_INSTALLATION,
        ):
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(VICTIM_INSTALLATION_ID),
                    "setup_action": "install",
                    "state": state,
                },
            )

        # 3. The attacker's workspace must NOT end up holding the victim's
        #    installation — that connection mints real tokens for their repos.
        assert not PlatformConnection.objects.filter(
            tenant=attacker_tenant, installation_id=VICTIM_INSTALLATION_ID
        ).exists()

    def test_installation_the_user_cannot_access_is_rejected(self):
        """GitHub is the authority: not in /user/installations, not connectable."""
        _, tenant = _login_owner(self.client)
        with mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="ghu_usertoken",
        ), mock.patch(
            "app.infrastructure.github_app.user_can_access_installation",
            return_value=False,
        ) as mock_access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_VICTIM_INSTALLATION,
        ) as mock_get:
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(VICTIM_INSTALLATION_ID),
                    "code": "stolen-or-own-code",
                    "setup_action": "install",
                },
            )
        mock_access.assert_called_once_with("ghu_usertoken", VICTIM_INSTALLATION_ID)
        mock_get.assert_not_called()
        assert not PlatformConnection.objects.filter(tenant=tenant).exists()

    def test_installation_the_user_can_access_is_accepted(self):
        """The legitimate direct-from-GitHub install: no state, but a valid code.

        A state-less callback asks which workspace before connecting (see
        ``test_github_app_direct_install``), so entitlement is what gets it as
        far as the confirmation.
        """
        _, tenant = _login_owner(self.client)
        with mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="ghu_usertoken",
        ), mock.patch(
            "app.infrastructure.github_app.user_can_access_installation",
            return_value=True,
        ), administers_account(), mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_VICTIM_INSTALLATION,
        ):
            resp = self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(VICTIM_INSTALLATION_ID),
                    "code": "own-code",
                    "setup_action": "install",
                },
            )
        assert resp.status_code == 200
        self.client.post(reverse("github_app_confirm"))
        assert PlatformConnection.objects.filter(
            tenant=tenant, installation_id=VICTIM_INSTALLATION_ID
        ).exists()

    @override_settings(GITHUB_APP_CLIENT_ID="", GITHUB_APP_CLIENT_SECRET="")
    def test_fails_closed_when_oauth_is_not_configured(self):
        """Without the OAuth credentials we cannot verify — so we refuse."""
        _, tenant = _login_owner(self.client)
        with mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_VICTIM_INSTALLATION,
        ) as mock_get:
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(VICTIM_INSTALLATION_ID),
                    "code": "own-code",
                },
            )
        mock_get.assert_not_called()
        assert not PlatformConnection.objects.filter(tenant=tenant).exists()
