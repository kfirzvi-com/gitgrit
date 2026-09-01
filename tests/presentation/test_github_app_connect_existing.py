"""Connecting an installation that already exists on GitHub.

Installing is a one-shot per account: once the App is on an organization,
``/installations/new`` stops producing a callback and shows the App's settings
page instead. Any workspace that wants that organization *after* the first one
therefore never gets an install callback, and before this flow existed it was
told to press the button it had just pressed.

So the entry point is authorization, which has no such limit, and the answer to
"which installations can you reach" is what gets offered. These tests drive the
request shapes GitHub actually sends — an authorize return carries a ``code``
and no ``installation_id`` — rather than a fabricated install callback, which is
what let the original gap sit behind a green test.
"""
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
from app.presentation.views.github_app_views import PENDING_CHOICES_SESSION_KEY
from tests.support import administers_account

ORG_INSTALLATION = {"id": 5001, "account_login": "kfirzvi-com", "account_type": "Organization"}
OTHER_INSTALLATION = {"id": 5002, "account_login": "acme-corp", "account_type": "Organization"}

APP_SETTINGS = dict(
    GITHUB_APP_ENABLED=True,
    GITHUB_APP_SLUG="gitgrit",
    GITHUB_APP_CLIENT_ID="Iv23test",
    GITHUB_APP_CLIENT_SECRET="secret",
)


def _reachable(installations):
    """Patch the two GitHub calls the authorize return makes."""
    return (
        mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            return_value="user-token",
        ),
        mock.patch(
            "app.infrastructure.github_app.list_user_installations",
            return_value=installations,
        ),
        administers_account(),
    )


@override_settings(**APP_SETTINGS)
class ConnectExistingInstallationTests(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(name="Alpha", slug="alpha")
        self.tenant_b = Tenant.objects.create(name="Beta", slug="beta")
        self.user = User.objects.create_user(
            username="admin", email="admin@example.com", password="pw"
        )
        Membership.objects.create(
            user=self.user, tenant=self.tenant_a, role=Membership.Role.OWNER
        )
        Membership.objects.create(
            user=self.user, tenant=self.tenant_b, role=Membership.Role.OWNER
        )
        self.client.force_login(self.user)

    def _activate(self, tenant):
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()

    def _authorize_return(self):
        """The shape GitHub sends back from /login/oauth/authorize."""
        return self.client.get(reverse("github_app_callback"), {"code": "oauth-code"})

    # ── the entry point ────────────────────────────────────────────────

    def test_button_sends_the_user_to_authorize_not_to_install(self):
        """The install page can only answer once per account; authorization
        can answer every time, so that is where the button points."""
        self._activate(self.tenant_a)

        resp = self.client.get(reverse("github_app_install"))

        self.assertEqual(resp.status_code, 302)
        self.assertIn("login/oauth/authorize", resp["Location"])
        self.assertIn("client_id=Iv23test", resp["Location"])
        self.assertNotIn("installations/new", resp["Location"])

    def test_install_new_still_goes_to_the_install_page(self):
        self._activate(self.tenant_a)

        resp = self.client.get(reverse("github_app_install_new"))

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/apps/gitgrit/installations/new", resp["Location"])
        self.assertIn("state=", resp["Location"])

    # ── the case that used to dead-end ─────────────────────────────────

    def test_second_workspace_can_connect_an_org_the_first_already_has(self):
        """The regression this flow exists for.

        Workspace A holds kfirzvi-com. B wants it too — a supported
        arrangement, since each workspace holds its own grant — but GitHub will
        not run an install for an account it is already on.
        """
        PlatformConnection.objects.create(
            tenant=self.tenant_a,
            platform=Platform.GITHUB,
            display_name="GitHub App (kfirzvi-com)",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=ORG_INSTALLATION["id"],
            account_login="kfirzvi-com",
        )
        self._activate(self.tenant_b)

        exchange, listing, reach = _reachable([ORG_INSTALLATION])
        with exchange, listing, reach:
            page = self._authorize_return()
            self.assertContains(page, "kfirzvi-com")
            resp = self.client.post(
                reverse("github_app_choose"),
                {"installation_id": str(ORG_INSTALLATION["id"])},
            )

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            PlatformConnection.objects.filter(
                tenant=self.tenant_b, installation_id=ORG_INSTALLATION["id"]
            ).exists()
        )
        # A is untouched — two independent grants, not a move.
        self.assertTrue(
            PlatformConnection.objects.filter(
                tenant=self.tenant_a, installation_id=ORG_INSTALLATION["id"]
            ).exists()
        )

    def test_the_picker_reveals_nothing_about_a_workspace_the_user_is_not_in(self):
        """B may learn that *it* can reach an account, never that someone else
        connected it.

        The workspace being hidden here belongs to a different user, so it must
        not show up at all — not by name, and not as "already connected", which
        would betray that somebody holds it.
        """
        other_owner = User.objects.create_user(
            username="other", email="other@example.com", password="pw"
        )
        hidden = Tenant.objects.create(name="HiddenCorp", slug="hidden")
        Membership.objects.create(
            user=other_owner, tenant=hidden, role=Membership.Role.OWNER
        )
        PlatformConnection.objects.create(
            tenant=hidden,
            platform=Platform.GITHUB,
            display_name="GitHub App (kfirzvi-com)",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=ORG_INSTALLATION["id"],
        )
        self._activate(self.tenant_b)

        exchange, listing, reach = _reachable([ORG_INSTALLATION])
        with exchange, listing, reach:
            page = self._authorize_return()

        body = page.content.decode()
        self.assertNotIn("HiddenCorp", body)
        self.assertNotIn("Already connected", body)
        # The account itself is still offered — B can reach it on GitHub.
        self.assertIn("kfirzvi-com", body)

    # ── choosing among several ─────────────────────────────────────────

    def test_several_reachable_installations_are_all_offered(self):
        self._activate(self.tenant_b)

        exchange, listing, reach = _reachable([ORG_INSTALLATION, OTHER_INSTALLATION])
        with exchange, listing, reach:
            page = self._authorize_return()

        self.assertContains(page, "kfirzvi-com")
        self.assertContains(page, "acme-corp")

    def test_an_installation_already_connected_here_is_marked(self):
        PlatformConnection.objects.create(
            tenant=self.tenant_b,
            platform=Platform.GITHUB,
            display_name="GitHub App (kfirzvi-com)",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=ORG_INSTALLATION["id"],
        )
        self._activate(self.tenant_b)

        exchange, listing, reach = _reachable([ORG_INSTALLATION, OTHER_INSTALLATION])
        with exchange, listing, reach:
            page = self._authorize_return()

        self.assertContains(page, "Already connected")

    def test_reconnecting_the_same_installation_updates_rather_than_duplicates(self):
        self._activate(self.tenant_b)
        exchange, listing, reach = _reachable([ORG_INSTALLATION])
        for _ in range(2):
            with exchange, listing, reach:
                self._authorize_return()
                self.client.post(
                    reverse("github_app_choose"),
                    {"installation_id": str(ORG_INSTALLATION["id"])},
                )

        self.assertEqual(
            PlatformConnection.objects.filter(
                tenant=self.tenant_b, installation_id=ORG_INSTALLATION["id"]
            ).count(),
            1,
        )

    # ── nothing to choose between ──────────────────────────────────────

    def test_no_reachable_installations_sends_the_user_to_install_one(self):
        """An empty list is not an error — it means nothing is set up yet."""
        self._activate(self.tenant_b)

        exchange, listing, reach = _reachable([])
        with exchange, listing, reach:
            resp = self._authorize_return()

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/apps/gitgrit/installations/new", resp["Location"])

    # ── the POST trusts only the choice ────────────────────────────────

    def test_posting_an_installation_github_did_not_vouch_for_is_refused(self):
        """The candidates come from the session, so naming another id here
        must not connect it — this is the same class of hole the entitlement
        check closed on the direct-install path."""
        self._activate(self.tenant_b)

        exchange, listing, reach = _reachable([ORG_INSTALLATION])
        with exchange, listing, reach:
            self._authorize_return()

        resp = self.client.post(
            reverse("github_app_choose"), {"installation_id": "999999"}
        )

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            PlatformConnection.objects.filter(installation_id=999999).exists()
        )

    def test_choosing_without_a_prior_authorize_is_refused(self):
        self._activate(self.tenant_b)

        resp = self.client.post(
            reverse("github_app_choose"),
            {"installation_id": str(ORG_INSTALLATION["id"])},
        )

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PlatformConnection.objects.exists())

    def test_switching_workspace_between_listing_and_choosing_is_refused(self):
        """The page named a workspace; attaching it somewhere else would be a
        silent surprise, so the parked choices carry the tenant they were for."""
        self._activate(self.tenant_b)
        exchange, listing, reach = _reachable([ORG_INSTALLATION])
        with exchange, listing, reach:
            self._authorize_return()

        self._activate(self.tenant_a)  # switched in another tab
        resp = self.client.post(
            reverse("github_app_choose"),
            {"installation_id": str(ORG_INSTALLATION["id"])},
        )

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            PlatformConnection.objects.filter(tenant=self.tenant_a).exists()
        )

    def test_candidates_are_cleared_after_use(self):
        self._activate(self.tenant_b)
        exchange, listing, reach = _reachable([ORG_INSTALLATION])
        with exchange, listing, reach:
            self._authorize_return()
            self.assertIn(PENDING_CHOICES_SESSION_KEY, self.client.session)
            self.client.post(
                reverse("github_app_choose"),
                {"installation_id": str(ORG_INSTALLATION["id"])},
            )

        self.assertNotIn(PENDING_CHOICES_SESSION_KEY, self.client.session)

    # ── permissions and failures ───────────────────────────────────────

    def test_a_plain_member_cannot_start_the_flow(self):
        tenant_c = Tenant.objects.create(name="Gamma", slug="gamma")
        Membership.objects.create(
            user=self.user, tenant=tenant_c, role=Membership.Role.MEMBER
        )
        self._activate(tenant_c)

        resp = self.client.get(reverse("github_app_install"))

        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("github.com", resp["Location"])

    def test_a_plain_member_cannot_choose(self):
        self._activate(self.tenant_b)
        exchange, listing, reach = _reachable([ORG_INSTALLATION])
        with exchange, listing, reach:
            self._authorize_return()

        Membership.objects.filter(user=self.user, tenant=self.tenant_b).update(
            role=Membership.Role.MEMBER
        )
        resp = self.client.post(
            reverse("github_app_choose"),
            {"installation_id": str(ORG_INSTALLATION["id"])},
        )

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PlatformConnection.objects.exists())

    def test_github_failing_to_answer_does_not_500(self):
        import requests as requests_lib

        self._activate(self.tenant_b)
        with mock.patch(
            "app.infrastructure.github_app.exchange_user_code",
            side_effect=requests_lib.RequestException("boom"),
        ):
            resp = self._authorize_return()

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PlatformConnection.objects.exists())


@override_settings(GITHUB_APP_ENABLED=False)
class DisabledFeatureTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Alpha", slug="alpha-off")
        self.user = User.objects.create_user(
            username="admin", email="a@example.com", password="pw"
        )
        Membership.objects.create(
            user=self.user, tenant=self.tenant, role=Membership.Role.OWNER
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def test_choose_is_unreachable(self):
        self.assertEqual(
            self.client.post(reverse("github_app_choose")).status_code, 404
        )

    def test_install_new_is_unreachable(self):
        self.assertEqual(
            self.client.get(reverse("github_app_install_new")).status_code, 404
        )
