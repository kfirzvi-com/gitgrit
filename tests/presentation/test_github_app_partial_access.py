"""A collaborator on one repository must not be able to attach the whole account.

Observed on staging. A workspace admin was an outside collaborator on two of the
five repositories in another person's personal installation, so
``GET /user/installations`` listed that installation for them — the endpoint
means "you can reach *something* here" — and their workspace connected it. The
connection mints installation-wide tokens and ``Add Project`` lists the
installation's own repository set, so the account's remaining private
repositories, ones that are a 404 for them on GitHub, became readable from their
workspace.

The check that has to hold is not about repositories at all: it is whether the
person owns the account the installation sits on, which is GitHub's own gate on
installing and uninstalling the App. These tests drive both callback shapes —
the picker returning from authorization, and a direct install from github.com —
through the app's own endpoints, patching GitHub at the listing seam so the real
decision runs.
"""
from __future__ import annotations

from unittest import mock

import pytest
import requests
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import PlatformConnection
from app.presentation.views.github_app_views import (
    PENDING_CHOICES_SESSION_KEY,
    PENDING_INSTALL_SESSION_KEY,
)
from tests.support import Patches

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

APP_SETTINGS = dict(
    GITHUB_APP_ENABLED=True,
    GITHUB_APP_SLUG="gitgrit",
    GITHUB_APP_CLIENT_ID="Iv23test",
    GITHUB_APP_CLIENT_SECRET="secret",
    STORAGES=NON_MANIFEST_STORAGES,
)

# The workspace admin who is connecting.
USER = {"id": 900001, "login": "workspace-admin"}

# Another person's personal account: five repositories, two of which the
# connecting user collaborates on.
PARTIAL_ID = 5101
OTHER_ACCOUNT_ID = 900002
PARTIAL_INSTALLATION = {
    "id": PARTIAL_ID,
    "account_id": OTHER_ACCOUNT_ID,
    "account_login": "another-dev",
    "account_type": "User",
}
PARTIAL_ACCOUNT = {
    "id": PARTIAL_ID,
    "account": {"login": "another-dev", "type": "User", "id": OTHER_ACCOUNT_ID},
}

# The org the connecting user owns.
OWNED_ID = 5102
OWNED_INSTALLATION = {
    "id": OWNED_ID,
    "account_id": 900101,
    "account_login": "acme-corp",
    "account_type": "Organization",
}
OWNED_ACCOUNT = {
    "id": OWNED_ID,
    "account": {"login": "acme-corp", "type": "Organization", "id": 900101},
}

# An org they merely belong to. Reaching every repository its installation
# covers today would not entitle them to what an owner adds to it tomorrow.
MEMBER_ID = 5103
MEMBER_INSTALLATION = {
    "id": MEMBER_ID,
    "account_id": 900102,
    "account_login": "globex",
    "account_type": "Organization",
}

ORG_ROLES = {"acme-corp": "admin", "globex": "member"}


def _login(client, tenant_name="test"):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant", name=tenant_name)
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


def _github(installations, account=None, org_roles=None, user=None):
    """Patch GitHub at the listing seam, so the real decision runs.

    Nothing here answers "is this user entitled" — the two listings GitHub
    offers about a person's own standing do, and the code under test draws the
    conclusion.
    """
    patches = [
        mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="ghu_usertoken",
        ),
        mock.patch(
            "app.infrastructure.github_app.list_user_installations",
            return_value=installations,
        ),
        mock.patch(
            "app.infrastructure.github_app.get_authenticated_user",
            return_value=dict(user or USER),
        ),
        mock.patch(
            "app.infrastructure.github_app.list_user_org_roles",
            return_value=dict(ORG_ROLES if org_roles is None else org_roles),
        ),
    ]
    if account is not None:
        patches.append(
            mock.patch(
                "app.infrastructure.github_app.get_installation",
                return_value=account,
            )
        )
    return Patches(*patches)


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestPickerWithholdsAccountsTheUserDoesNotOwn(TestCase):
    """The authorize return, which is how the staging breach actually happened."""

    def test_someone_elses_personal_installation_is_not_offered(self):
        _login(self.client)
        with _github([PARTIAL_INSTALLATION]):
            resp = self.client.get(
                reverse("github_app_callback"), {"code": "oauth-code"}, follow=True
            )

        body = resp.content.decode()
        self.assertNotIn(f'value="{PARTIAL_ID}"', body)
        # It must not be parked as a candidate either — the POST reads the
        # session, so a hidden-but-stored installation is still connectable.
        pending = self.client.session.get(PENDING_CHOICES_SESSION_KEY) or {}
        self.assertNotIn(
            PARTIAL_ID, [i["id"] for i in pending.get("installations", [])]
        )

    def test_an_org_the_user_only_belongs_to_is_not_offered(self):
        """Membership is not ownership, however much of the org one can read."""
        _login(self.client)
        with _github([MEMBER_INSTALLATION]):
            resp = self.client.get(
                reverse("github_app_callback"), {"code": "oauth-code"}, follow=True
            )

        self.assertNotIn(f'value="{MEMBER_ID}"', resp.content.decode())

    def test_an_owned_org_is_still_offered(self):
        _login(self.client)
        with _github([OWNED_INSTALLATION]):
            resp = self.client.get(
                reverse("github_app_callback"), {"code": "oauth-code"}
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn(f'value="{OWNED_ID}"', resp.content.decode())

    def test_the_owned_org_survives_alongside_the_withheld_accounts(self):
        _login(self.client)
        with _github(
            [PARTIAL_INSTALLATION, OWNED_INSTALLATION, MEMBER_INSTALLATION]
        ):
            resp = self.client.get(
                reverse("github_app_callback"), {"code": "oauth-code"}
            )

        body = resp.content.decode()
        self.assertIn(f'value="{OWNED_ID}"', body)
        self.assertNotIn(f'value="{PARTIAL_ID}"', body)
        self.assertNotIn(f'value="{MEMBER_ID}"', body)

    def test_posting_a_withheld_installation_id_connects_nothing(self):
        """Forging the radio value must not get past the session candidates."""
        _, tenant = _login(self.client)
        with _github([PARTIAL_INSTALLATION, OWNED_INSTALLATION]):
            self.client.get(reverse("github_app_callback"), {"code": "oauth-code"})
            self.client.post(
                reverse("github_app_choose"), {"installation_id": str(PARTIAL_ID)}
            )

        self.assertFalse(
            PlatformConnection.objects.filter(
                tenant=tenant, installation_id=PARTIAL_ID
            ).exists()
        )

    def test_asks_github_about_the_user_once_for_the_whole_list(self):
        """The cost is the batch's, not each candidate's."""
        _login(self.client)
        with _github(
            [PARTIAL_INSTALLATION, OWNED_INSTALLATION, MEMBER_INSTALLATION]
        ):
            from app.infrastructure import github_app

            self.client.get(reverse("github_app_callback"), {"code": "oauth-code"})
            self.assertEqual(github_app.list_user_org_roles.call_count, 1)
            self.assertEqual(github_app.get_authenticated_user.call_count, 1)

    def test_a_github_error_offers_nothing_rather_than_blaming_the_user(self):
        _, tenant = _login(self.client)
        with mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="ghu_usertoken",
        ), mock.patch(
            "app.infrastructure.github_app.list_user_installations",
            return_value=[OWNED_INSTALLATION],
        ), mock.patch(
            "app.infrastructure.github_app.list_user_org_roles",
            side_effect=requests.RequestException("boom"),
        ):
            resp = self.client.get(
                reverse("github_app_callback"), {"code": "oauth-code"}, follow=True
            )

        self.assertNotIn(f'value="{OWNED_ID}"', resp.content.decode())
        self.assertIsNone(self.client.session.get(PENDING_CHOICES_SESSION_KEY))
        self.assertFalse(PlatformConnection.objects.filter(tenant=tenant).exists())


@pytest.mark.django_db
@override_settings(**APP_SETTINGS)
class TestDirectCallbackRefusesAccountsTheUserDoesNotOwn(TestCase):
    """The other shape: a callback naming one installation id outright."""

    def test_stateless_install_of_someone_elses_account_is_refused(self):
        _, tenant = _login(self.client)
        with _github([PARTIAL_INSTALLATION], account=PARTIAL_ACCOUNT):
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(PARTIAL_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                },
            )

        self.assertIsNone(self.client.session.get(PENDING_INSTALL_SESSION_KEY))
        # And confirming anyway connects nothing.
        self.client.post(reverse("github_app_confirm"))
        self.assertFalse(PlatformConnection.objects.filter(tenant=tenant).exists())

    def test_install_from_settings_of_someone_elses_account_is_refused(self):
        """Same refusal on the state-carrying path, which connects in one hop."""
        _, tenant = _login(self.client)
        resp = self.client.get(reverse("github_app_install"))
        state = resp.headers["Location"].split("state=")[1]

        with _github([PARTIAL_INSTALLATION], account=PARTIAL_ACCOUNT):
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(PARTIAL_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                    "state": state,
                },
            )

        self.assertFalse(PlatformConnection.objects.filter(tenant=tenant).exists())

    def test_the_refusal_does_not_name_the_account(self):
        """One message has to serve "someone else's" and "does not exist"."""
        _, tenant = _login(self.client)
        with _github([PARTIAL_INSTALLATION], account=PARTIAL_ACCOUNT):
            resp = self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(PARTIAL_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                },
                follow=True,
            )

        text = " ".join(str(m) for m in resp.context["messages"])
        self.assertIn("owner", text)
        self.assertNotIn("another-dev", text)

    def test_an_owned_org_still_connects_in_one_hop(self):
        _, tenant = _login(self.client)
        resp = self.client.get(reverse("github_app_install"))
        state = resp.headers["Location"].split("state=")[1]

        with _github([OWNED_INSTALLATION], account=OWNED_ACCOUNT):
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(OWNED_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                    "state": state,
                },
            )

        self.assertTrue(
            PlatformConnection.objects.filter(
                tenant=tenant, installation_id=OWNED_ID
            ).exists()
        )

    def test_the_owner_of_a_personal_account_still_connects_it(self):
        """The account's own owner connecting it, which must keep working."""
        _, tenant = _login(self.client)
        owner = {"id": OTHER_ACCOUNT_ID, "login": "another-dev"}
        with _github(
            [PARTIAL_INSTALLATION], account=PARTIAL_ACCOUNT, user=owner, org_roles={}
        ):
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(PARTIAL_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                },
            )
            self.client.post(reverse("github_app_confirm"))

        self.assertTrue(
            PlatformConnection.objects.filter(
                tenant=tenant, installation_id=PARTIAL_ID
            ).exists()
        )

    def test_entitlement_never_mints_an_installation_token(self):
        """It asks about the account, not about repositories.

        Nothing in the decision reads the installation's repository list, so an
        owner is not refused because a repository they are not a collaborator on
        sits inside their own organization — and no private repository name is
        fetched to decide a refusal.
        """
        _, tenant = _login(self.client)
        resp = self.client.get(reverse("github_app_install"))
        state = resp.headers["Location"].split("state=")[1]

        with _github([OWNED_INSTALLATION], account=OWNED_ACCOUNT), mock.patch(
            "app.infrastructure.github_app.get_installation_token",
            side_effect=AssertionError("the entitlement check minted a token"),
        ):
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(OWNED_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                    "state": state,
                },
            )

        self.assertTrue(
            PlatformConnection.objects.filter(
                tenant=tenant, installation_id=OWNED_ID
            ).exists()
        )

    def test_fails_closed_when_github_cannot_be_asked(self):
        """GitHub erroring mid-check must not fall through to connecting."""
        _, tenant = _login(self.client)
        with mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="ghu_usertoken",
        ), mock.patch(
            "app.infrastructure.github_app.list_user_installations",
            return_value=[PARTIAL_INSTALLATION],
        ), mock.patch(
            "app.infrastructure.github_app.get_installation",
            side_effect=requests.RequestException("boom"),
        ):
            self.client.get(
                reverse("github_app_callback"),
                {
                    "installation_id": str(PARTIAL_ID),
                    "setup_action": "install",
                    "code": "oauth-code",
                },
            )

        self.assertFalse(PlatformConnection.objects.filter(tenant=tenant).exists())
        self.assertIsNone(self.client.session.get(PENDING_INSTALL_SESSION_KEY))
