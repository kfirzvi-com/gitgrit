"""What happens when the install flow doesn't go to plan.

The happy paths live in ``test_github_app_callback``,
``test_github_app_direct_install`` and ``test_github_app_install_entitlement``.
This file covers the ways a real install goes sideways: GitHub answering with an
error, the feature being switched off, someone without permission trying, and
the user changing workspace halfway through. None of them may 500, and none may
attach an installation somewhere the user wasn't told about.
"""
from unittest import mock

import jwt
import pytest
import requests
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AuthMethod, PlatformConnection
from app.presentation.views.github_app_views import PENDING_INSTALL_SESSION_KEY

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
    _activate(client, tenant)
    return user, tenant


def _activate(client, tenant):
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()


def _entitled():
    """Patch the entitlement pair so only ``get_installation`` is under test."""
    return (
        mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="ghu_usertoken",
        ),
        mock.patch(
            "app.infrastructure.github_app.user_can_access_installation",
            return_value=True,
        ),
    )


def _messages(response):
    return [str(m) for m in response.wsgi_request._messages]


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestGitHubUnavailable(TestCase):
    """GitHub erroring is a bad day, not a crash.

    A callback URL replayed after the installation was deleted 404s, and the
    API has its own outages. Both used to reach the user as a 500.
    """

    def test_unreadable_installation_does_not_500(self):
        _login(self.client)
        exchange, access = _entitled()
        with exchange, access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            side_effect=requests.HTTPError("404 Not Found"),
        ):
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": str(INSTALLATION_ID), "code": "oauth-code"},
            )
        assert resp.status_code == 302
        assert not PlatformConnection.objects.exists()
        assert any("Couldn't read that installation" in m for m in _messages(resp))

    def test_network_failure_is_reported_not_raised(self):
        _login(self.client)
        exchange, access = _entitled()
        with exchange, access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            side_effect=requests.ConnectionError("dns"),
        ):
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": str(INSTALLATION_ID), "code": "oauth-code"},
            )
        assert resp.status_code == 302
        assert not PlatformConnection.objects.exists()

    def test_refresh_path_survives_an_unreadable_installation(self):
        """The no-code refresh reads the installation too, and could also 500."""
        _, tenant = _login(self.client)
        PlatformConnection.objects.create(
            tenant=tenant,
            platform="github",
            display_name="GitHub App (acme)",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=INSTALLATION_ID,
            account_login="acme",
        )
        with mock.patch(
            "app.infrastructure.github_app.get_installation",
            side_effect=requests.HTTPError("404 Not Found"),
        ):
            resp = self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(INSTALLATION_ID),
                    "setup_action": "update",
                },
            )
        assert resp.status_code == 302
        # The existing connection is left exactly as it was.
        conn = PlatformConnection.objects.get(tenant=tenant)
        assert conn.account_login == "acme"

    def test_a_malformed_private_key_is_reported_not_raised(self):
        """Availability checks the key is present, never that it parses.

        A truncated key, or one whose ``\\n`` escapes didn't survive the deploy,
        turns the feature on and then fails at the first signature.
        """
        _login(self.client)
        exchange, access = _entitled()
        with exchange, access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            side_effect=jwt.InvalidKeyError("Could not parse the provided key."),
        ):
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": str(INSTALLATION_ID), "code": "oauth-code"},
            )
        assert resp.status_code == 302
        assert not PlatformConnection.objects.exists()

    def test_installation_without_an_account_still_connects(self):
        """GitHub omitting ``account`` shouldn't strand an otherwise valid install."""
        _, tenant = _login(self.client)
        exchange, access = _entitled()
        with exchange, access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value={"id": INSTALLATION_ID, "account": None},
        ):
            self.client.get(
                reverse("github_app_callback"),
                {"installation_id": str(INSTALLATION_ID), "code": "oauth-code"},
            )
            self.client.post(reverse("github_app_confirm"))
        conn = PlatformConnection.objects.get(tenant=tenant)
        assert conn.display_name == "GitHub App"
        assert conn.account_login == ""


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestWorkspaceTargeting(TestCase):
    """An installation lands in the workspace the user was shown — or nowhere."""

    def _park_pending_install(self, expected_name):
        exchange, access = _entitled()
        with exchange, access, mock.patch(
            "app.infrastructure.github_app.get_installation",
            return_value=_INSTALLATION,
        ):
            resp = self.client.get(
                reverse("github_app_callback"),
                {"installation_id": str(INSTALLATION_ID), "code": "oauth-code"},
            )
        assert expected_name in resp.content.decode()
        return resp

    def test_switching_workspace_before_confirming_connects_nothing(self):
        """The page named Alpha; the button must not quietly wire up Bravo."""
        user, _alpha = _login(self.client, tenant_name="Alpha")
        bravo = baker.make("app.Tenant", name="Bravo")
        baker.make("app.Membership", user=user, tenant=bravo, role="owner")

        self._park_pending_install("Alpha")
        _activate(self.client, bravo)  # switched in another tab

        resp = self.client.post(reverse("github_app_confirm"))
        assert resp.status_code == 302
        assert not PlatformConnection.objects.exists()
        assert any("active workspace changed" in m for m in _messages(resp))

    def test_a_rejected_confirm_does_not_leave_the_install_pending(self):
        """One shot: the stale pending entry is consumed, not left to fire later."""
        user, _alpha = _login(self.client, tenant_name="Alpha")
        bravo = baker.make("app.Tenant", name="Bravo")
        baker.make("app.Membership", user=user, tenant=bravo, role="owner")

        self._park_pending_install("Alpha")
        _activate(self.client, bravo)
        self.client.post(reverse("github_app_confirm"))

        assert PENDING_INSTALL_SESSION_KEY not in self.client.session

    def test_confirming_in_the_same_workspace_still_works(self):
        """The guard must not break the ordinary path it protects."""
        _, alpha = _login(self.client, tenant_name="Alpha")
        self._park_pending_install("Alpha")
        resp = self.client.post(reverse("github_app_confirm"))
        assert resp.status_code == 302
        conn = PlatformConnection.objects.get(tenant=alpha)
        assert conn.installation_id == INSTALLATION_ID


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestPermissions(TestCase):
    def test_member_cannot_start_an_install(self):
        _login(self.client, role="member")
        resp = self.client.get(reverse("github_app_install"))
        assert resp.status_code == 302
        assert resp["Location"] == reverse("tenant_settings")
        assert any("don't have permission" in m for m in _messages(resp))

    def test_member_cannot_finish_an_install(self):
        """Demotion mid-flow, or a hand-crafted callback from a member."""
        _login(self.client, role="member")
        resp = self.client.get(
            reverse("github_app_callback"),
            {"installation_id": str(INSTALLATION_ID), "code": "oauth-code"},
        )
        assert resp.status_code == 302
        assert not PlatformConnection.objects.exists()

    def test_member_cannot_confirm_an_install(self):
        _login(self.client, role="member")
        resp = self.client.post(reverse("github_app_confirm"))
        assert resp.status_code == 302
        assert not PlatformConnection.objects.exists()

    def test_admin_may_install(self):
        """ADMIN is allowed alongside OWNER — the redirect goes out to GitHub."""
        _login(self.client, role="admin")
        resp = self.client.get(reverse("github_app_install"))
        assert resp.status_code == 302
        assert resp["Location"].startswith(
            "https://github.com/login/oauth/authorize?client_id="
        )


@pytest.mark.django_db
@override_settings(GITHUB_APP_ENABLED=False, STORAGES=NON_MANIFEST_STORAGES)
class TestKillSwitch(TestCase):
    """A disabled App leaves no reachable surface, not just a hidden button."""

    def test_every_entry_point_is_gone(self):
        _login(self.client)
        assert self.client.get(reverse("github_app_install")).status_code == 404
        assert self.client.get(reverse("github_app_callback")).status_code == 404
        assert self.client.post(reverse("github_app_confirm")).status_code == 404

    def test_a_pending_install_cannot_be_redeemed_after_a_shutdown(self):
        """Turning the feature off mid-flow closes the door behind it."""
        _, tenant = _login(self.client)
        session = self.client.session
        session[PENDING_INSTALL_SESSION_KEY] = {
            "installation_id": INSTALLATION_ID,
            "account_login": "acme",
            "account_type": "Organization",
            "tenant_id": str(tenant.id),
        }
        session.save()
        assert self.client.post(reverse("github_app_confirm")).status_code == 404
        assert not PlatformConnection.objects.exists()


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestMalformedCallbacks(TestCase):
    def test_missing_installation_id_and_no_code_is_reported(self):
        """Neither shape: not an install return, not an authorize return."""
        _login(self.client)
        resp = self.client.get(reverse("github_app_callback"))
        assert resp.status_code == 302
        assert any("did not return an installation id" in m for m in _messages(resp))

    def test_unreadable_installation_id_is_reported(self):
        _login(self.client)
        resp = self.client.get(
            reverse("github_app_callback"),
            {"installation_id": "not-a-number", "code": "c"},
        )
        assert resp.status_code == 302
        assert any("unreadable installation id" in m for m in _messages(resp))
        assert not PlatformConnection.objects.exists()

    def test_confirm_rejects_a_get(self):
        """State-changing, so POST-only."""
        _login(self.client)
        assert self.client.get(reverse("github_app_confirm")).status_code == 405
