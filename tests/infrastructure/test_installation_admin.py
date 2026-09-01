"""Who may attach a GitHub App installation to a workspace.

``GET /user/installations`` cannot answer it. GitHub lists an installation there
as soon as the user has explicit read/write/admin on **one** of its
repositories, so an outside collaborator on a single repo qualifies — while a
connection holds the whole installation, mints installation-wide tokens, and
lists the installation's own repository set in Add Project.

The question that actually has to hold is not about repositories at all: does
this person administer the account the installation sits on? That is GitHub's
own gate on installing and uninstalling the App, and GitHub answers it in two
calls that need no App permission — ``GET /user`` for their own account, and
``GET /user/memberships/orgs`` for their role in every organization they belong
to. These tests pin both listings and the decision over them.

``SimpleTestCase`` subclasses rather than bare pytest functions: CI runs
``manage.py test``, which collects only TestCase subclasses.
"""
from __future__ import annotations

from unittest import mock

import requests
from django.test import SimpleTestCase

from app.infrastructure import github_app

# Someone else's personal account, and the installation on it: the shape of the
# case found on staging.
OTHER_USER_ID = 900002
OTHER_INSTALLATION_ID = 5101

# The person connecting, an outside collaborator on two of that installation's
# repositories and nothing more.
USER_ID = 900001


class _Resp:
    def __init__(self, json_data):
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


def _membership(login, role, state="active"):
    return {"organization": {"login": login}, "role": role, "state": state}


class TestGetAuthenticatedUser(SimpleTestCase):
    """Naming the connecting user, so a personal installation can be matched."""

    def test_asks_the_user_endpoint_with_the_user_token(self):
        seen = {}

        def fake_get(url, headers=None, params=None, timeout=None):
            seen["url"] = url
            seen["auth"] = (headers or {}).get("Authorization")
            return _Resp({"id": USER_ID, "login": "workspace-admin"})

        with mock.patch.object(github_app.requests, "get", fake_get):
            user = github_app.get_authenticated_user("ghu_usertoken")

        self.assertEqual(seen["url"], "https://api.github.com/user")
        self.assertEqual(seen["auth"], "Bearer ghu_usertoken")
        self.assertEqual(user["id"], USER_ID)


class TestListUserOrgRoles(SimpleTestCase):
    """The user's role in each organization, from their own token.

    ``GET /user/memberships/orgs`` is the cheap half of this: it works with a
    GitHub App user access token and requires no App permission, so nothing
    here asks an existing installation to accept a new one.
    """

    def test_asks_the_memberships_endpoint_with_the_user_token(self):
        seen = {}

        def fake_get(url, headers=None, params=None, timeout=None):
            seen["url"] = url
            seen["auth"] = (headers or {}).get("Authorization")
            return _Resp([_membership("acme-corp", "admin")])

        with mock.patch.object(github_app.requests, "get", fake_get):
            roles = github_app.list_user_org_roles("ghu_usertoken")

        self.assertEqual(seen["url"], "https://api.github.com/user/memberships/orgs")
        self.assertEqual(seen["auth"], "Bearer ghu_usertoken")
        self.assertEqual(roles, {"acme-corp": "admin"})

    def test_keys_are_lowered_so_a_login_can_be_matched_either_way(self):
        with mock.patch.object(
            github_app.requests,
            "get",
            lambda *a, **k: _Resp([_membership("Acme-Corp", "admin")]),
        ):
            self.assertEqual(
                github_app.list_user_org_roles("t"), {"acme-corp": "admin"}
            )

    def test_drops_memberships_that_are_not_active(self):
        """A pending invitation is not membership, whatever role it offers."""
        with mock.patch.object(
            github_app.requests,
            "get",
            lambda *a, **k: _Resp(
                [
                    _membership("globex", "admin", state="pending"),
                    _membership("acme-corp", "admin"),
                ]
            ),
        ):
            self.assertEqual(
                github_app.list_user_org_roles("t"), {"acme-corp": "admin"}
            )

    def test_paginates(self):
        """A plain array, so the short page ends the walk rather than a count."""
        pages = {
            1: [_membership(f"org{i}", "member") for i in range(100)],
            2: [_membership("last-org", "admin")],
        }

        def fake_get(url, headers=None, params=None, timeout=None):
            return _Resp(pages[params["page"]])

        with mock.patch.object(github_app.requests, "get", fake_get):
            roles = github_app.list_user_org_roles("t")

        self.assertEqual(len(roles), 101)
        self.assertEqual(roles["last-org"], "admin")


class TestAccountAuthority(SimpleTestCase):
    """The decision: does this user administer the account, or not."""

    def _authority(self, *, user_id=USER_ID, org_roles=None):
        """An authority with both answers already in hand.

        Warmed inside the patch so the assertions that follow need no live
        GitHub — the caching itself is pinned separately, below.
        """
        authority = github_app.AccountAuthority("ghu_usertoken")
        with mock.patch.object(
            github_app, "get_authenticated_user", return_value={"id": user_id}
        ), mock.patch.object(
            github_app, "list_user_org_roles", return_value=dict(org_roles or {})
        ):
            authority.user_id
            authority.admin_orgs
        return authority

    # -- personal accounts ------------------------------------------------

    def test_a_user_administers_their_own_account(self):
        authority = self._authority(user_id=USER_ID)
        self.assertTrue(authority.administers("User", "workspace-admin", USER_ID))

    def test_a_collaborator_does_not_administer_someone_elses_account(self):
        """The staging case: a collaborator on two of the account's repositories,
        which is not the same as the person whose account it is."""
        authority = self._authority(user_id=USER_ID)
        self.assertFalse(authority.administers("User", "another-dev", OTHER_USER_ID))

    def test_falls_back_to_the_login_when_no_account_id_is_known(self):
        authority = github_app.AccountAuthority("t")
        with mock.patch.object(
            github_app,
            "get_authenticated_user",
            return_value={"id": USER_ID, "login": "Workspace-Admin"},
        ):
            self.assertTrue(authority.administers("User", "workspace-admin", None))
            self.assertFalse(authority.administers("User", "another-dev", None))

    # -- organizations ----------------------------------------------------

    def test_an_org_admin_administers_the_org(self):
        authority = self._authority(org_roles={"acme-corp": "admin"})
        self.assertTrue(authority.administers("Organization", "acme-corp", 42))

    def test_matches_the_org_login_case_insensitively(self):
        authority = self._authority(org_roles={"acme-corp": "admin"})
        self.assertTrue(authority.administers("Organization", "Acme-Corp", 42))

    def test_a_plain_member_does_not_administer_the_org(self):
        """Reaching every repository an installation covers is not the same as
        being entitled to what it will cover tomorrow."""
        authority = self._authority(org_roles={"acme-corp": "member"})
        self.assertFalse(authority.administers("Organization", "acme-corp", 42))

    def test_a_billing_manager_does_not_administer_the_org(self):
        authority = self._authority(org_roles={"acme-corp": "billing_manager"})
        self.assertFalse(authority.administers("Organization", "acme-corp", 42))

    def test_a_non_member_does_not_administer_the_org(self):
        """An outside collaborator has no membership at all."""
        authority = self._authority(org_roles={"acme-corp": "admin"})
        self.assertFalse(authority.administers("Organization", "globex", 42))

    # -- anything else ----------------------------------------------------

    def test_an_unrecognised_account_type_is_refused(self):
        """Enterprise-level installs and future shapes fail closed."""
        authority = self._authority(org_roles={"acme-corp": "admin"})
        self.assertFalse(authority.administers("Enterprise", "acme-corp", 42))
        self.assertFalse(authority.administers("", "acme-corp", 42))

    # -- cost -------------------------------------------------------------

    def test_asks_github_once_however_many_candidates_are_checked(self):
        authority = github_app.AccountAuthority("t")
        with mock.patch.object(
            github_app, "get_authenticated_user", return_value={"id": USER_ID}
        ) as user, mock.patch.object(
            github_app, "list_user_org_roles", return_value={"a": "admin"}
        ) as roles:
            for i in range(5):
                authority.administers("Organization", f"org{i}", i)
                authority.administers("User", "workspace-admin", USER_ID)

        self.assertEqual(user.call_count, 1)
        self.assertEqual(roles.call_count, 1)

    def test_asks_only_the_question_the_candidates_raise(self):
        """Org-only candidates never need the user's own account, or vice versa."""
        authority = github_app.AccountAuthority("t")
        with mock.patch.object(
            github_app, "get_authenticated_user"
        ) as user, mock.patch.object(
            github_app, "list_user_org_roles", return_value={"acme": "admin"}
        ) as roles:
            authority.administers("Organization", "acme", 42)

        user.assert_not_called()
        self.assertEqual(roles.call_count, 1)


class TestUserAdministersInstallation(SimpleTestCase):
    """Resolving an installation id, which is all a callback hands us."""

    def test_reads_the_account_off_the_installation_and_decides(self):
        with mock.patch.object(
            github_app,
            "get_installation",
            return_value={
                "id": OTHER_INSTALLATION_ID,
                "account": {"login": "another-dev", "type": "User", "id": OTHER_USER_ID},
            },
        ), mock.patch.object(
            github_app, "get_authenticated_user", return_value={"id": USER_ID}
        ):
            self.assertFalse(
                github_app.user_administers_installation("ghu_t", OTHER_INSTALLATION_ID)
            )

    def test_says_yes_for_the_account_owner(self):
        with mock.patch.object(
            github_app,
            "get_installation",
            return_value={
                "id": OTHER_INSTALLATION_ID,
                "account": {"login": "another-dev", "type": "User", "id": OTHER_USER_ID},
            },
        ), mock.patch.object(
            github_app, "get_authenticated_user", return_value={"id": OTHER_USER_ID}
        ):
            self.assertTrue(
                github_app.user_administers_installation("ghu_t", OTHER_INSTALLATION_ID)
            )

    def test_a_github_error_propagates_so_callers_fail_closed(self):
        with mock.patch.object(
            github_app,
            "get_installation",
            side_effect=requests.RequestException("boom"),
        ):
            with self.assertRaises(requests.RequestException):
                github_app.user_administers_installation("ghu_t", OTHER_INSTALLATION_ID)
