"""Tests for PlatformConnection.get_access_token — the auth-method seam.

PAT connections return the stored token verbatim; GitHub App connections mint a
short-lived installation token (mocked here, since no real App exists yet).

``TestCase`` subclasses rather than bare pytest functions: CI runs
``manage.py test``, which collects only TestCase subclasses. Model instances are
built directly rather than with model_bakery, which cannot generate the
EncryptedCharField on this model.
"""
from unittest import mock

from django.test import TestCase

from app.domain.models import AuthMethod, Platform, PlatformConnection, Tenant


class GetAccessTokenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name="Acme", slug="acme")

    def test_pat_connection_returns_stored_token(self):
        conn = PlatformConnection.objects.create(
            tenant=self.tenant,
            platform=Platform.GITHUB,
            display_name="PAT conn",
            auth_method=AuthMethod.PAT,
            access_token="ghp_stored_pat",
        )
        self.assertEqual(conn.get_access_token(), "ghp_stored_pat")

    def test_github_app_connection_mints_installation_token(self):
        conn = PlatformConnection.objects.create(
            tenant=self.tenant,
            platform=Platform.GITHUB,
            display_name="App conn",
            auth_method=AuthMethod.GITHUB_APP,
            access_token=None,
            installation_id=777,
        )
        with mock.patch(
            "app.infrastructure.github_app.get_installation_token",
            return_value="ghs_minted",
        ) as mock_mint:
            token = conn.get_access_token(repositories=["acme/app"])

        self.assertEqual(token, "ghs_minted")
        mock_mint.assert_called_once_with(777, ["acme/app"])

    def test_app_connection_stores_no_token_at_rest(self):
        conn = PlatformConnection.objects.create(
            tenant=self.tenant,
            platform=Platform.GITHUB,
            display_name="App conn",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=778,
        )
        conn.refresh_from_db()
        self.assertFalse(conn.access_token)


class ScopedTokenReachesGitHubCorrectlyTests(TestCase):
    """End to end through the seam: what a caller passes is what GitHub gets.

    The unit test above pins the arguments handed to ``get_installation_token``;
    this one goes one layer further, to the HTTP body, because that is where the
    owner-qualified path was being rejected with a 422.
    """

    def setUp(self):
        from app.infrastructure import github_app

        self.github_app = github_app
        github_app._token_cache.clear()
        self.addCleanup(github_app._token_cache.clear)

        self.tenant = Tenant.objects.create(name="Acme", slug="acme-scoped")
        self.conn = PlatformConnection.objects.create(
            tenant=self.tenant,
            platform=Platform.GITHUB,
            display_name="App conn",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=901,
        )

    def test_full_path_arrives_at_github_as_a_bare_repo_name(self):
        resp = mock.Mock()
        resp.raise_for_status = mock.Mock()
        resp.json.return_value = {
            "token": "ghs_scoped",
            "expires_at": "2099-01-01T00:00:00Z",
        }

        with mock.patch.object(self.github_app, "build_app_jwt", return_value="j"), \
                mock.patch.object(
                    self.github_app.requests, "post", return_value=resp
                ) as mock_post:
            token = self.conn.get_access_token(repositories=["acme/app"])

        self.assertEqual(token, "ghs_scoped")
        self.assertEqual(mock_post.call_args.kwargs["json"]["repositories"], ["app"])
        self.assertIn(
            "/app/installations/901/access_tokens", mock_post.call_args[0][0]
        )
