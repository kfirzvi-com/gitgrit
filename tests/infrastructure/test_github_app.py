"""Unit tests for the GitHub App installation-token minting service.

No real GitHub App exists yet, so every HTTP exchange is mocked. These tests
pin: (1) the App JWT is a valid RS256 token with the expected claims, (2) an
installation token is returned, (3) a second call within the token's TTL is
served from cache without a second HTTP request, and (4) repository scoping is
sent in the form GitHub actually accepts.

Written as ``SimpleTestCase`` subclasses, not bare pytest functions: CI runs
``manage.py test``, whose unittest loader collects only ``TestCase`` subclasses.
As plain functions these assertions never executed anywhere but a local pytest.
"""
from __future__ import annotations

import time
from unittest import mock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import SimpleTestCase, override_settings

from app.infrastructure import github_app


def _generate_private_key_pem() -> tuple[str, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def _mock_token_response(expires_in_seconds: int = 3600, token: str = "ghs_installtoken"):
    expires_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in_seconds)
    )
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = {"token": token, "expires_at": expires_at}
    return resp


class GitHubAppTokenCacheTestCase(SimpleTestCase):
    """Base class clearing the module-level token cache around each test."""

    def setUp(self):
        github_app._token_cache.clear()
        self.addCleanup(github_app._token_cache.clear)


class TestBuildAppJWT(SimpleTestCase):
    def test_is_valid_rs256_with_expected_claims(self):
        pem, public_key = _generate_private_key_pem()
        with override_settings(GITHUB_APP_ID="123456", GITHUB_APP_PRIVATE_KEY=pem):
            token = github_app.build_app_jwt()

        decoded = jwt.decode(token, public_key, algorithms=["RS256"])
        self.assertEqual(decoded["iss"], "123456")
        # GitHub caps the App JWT lifetime at 10 minutes.
        self.assertLessEqual(decoded["exp"] - decoded["iat"], 600)


class TestGetInstallationToken(GitHubAppTokenCacheTestCase):
    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_returns_token(self, mock_post, _mock_jwt):
        mock_post.return_value = _mock_token_response()
        token = github_app.get_installation_token(42)
        self.assertEqual(token, "ghs_installtoken")
        mock_post.assert_called_once()

    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_second_call_within_ttl_is_a_cache_hit(self, mock_post, _mock_jwt):
        mock_post.return_value = _mock_token_response()
        first = github_app.get_installation_token(42)
        second = github_app.get_installation_token(42)
        self.assertEqual(first, "ghs_installtoken")
        self.assertEqual(second, "ghs_installtoken")
        # Cached: no second HTTP request.
        mock_post.assert_called_once()

    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_different_repo_scope_mints_a_separate_token(self, mock_post, _mock_jwt):
        mock_post.side_effect = [
            _mock_token_response(token="tok-all"),
            _mock_token_response(token="tok-scoped"),
        ]
        all_token = github_app.get_installation_token(42)
        scoped_token = github_app.get_installation_token(42, repositories=["acme/app"])
        self.assertEqual(all_token, "tok-all")
        self.assertEqual(scoped_token, "tok-scoped")
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_expired_cached_token_is_refetched(self, mock_post, _mock_jwt):
        # First token already past its safety buffer, so the next call refetches.
        mock_post.side_effect = [
            _mock_token_response(expires_in_seconds=30, token="tok-old"),
            _mock_token_response(token="tok-new"),
        ]
        first = github_app.get_installation_token(42)
        second = github_app.get_installation_token(42)
        self.assertEqual(first, "tok-old")
        self.assertEqual(second, "tok-new")
        self.assertEqual(mock_post.call_count, 2)


class TestRepositoryScopeIsSentAsGitHubExpects(GitHubAppTokenCacheTestCase):
    """GitHub scopes an installation token by repository name *relative to the
    installation* — ``"app"``, never ``"acme/app"``. Callers hold owner-qualified
    ``full_path`` values, so sending them through unchanged is a 422 and a standard
    run that silently never happens.
    """

    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_owner_prefix_is_stripped_from_the_request_body(self, mock_post, _mock_jwt):
        mock_post.return_value = _mock_token_response()

        github_app.get_installation_token(42, repositories=["acme/app"])

        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["repositories"], ["app"])

    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_bare_names_pass_through_unchanged(self, mock_post, _mock_jwt):
        mock_post.return_value = _mock_token_response()

        github_app.get_installation_token(42, repositories=["app"])

        self.assertEqual(mock_post.call_args.kwargs["json"]["repositories"], ["app"])

    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_every_entry_is_normalized(self, mock_post, _mock_jwt):
        mock_post.return_value = _mock_token_response()

        github_app.get_installation_token(
            42, repositories=["acme/app", "other/service", "bare"]
        )

        self.assertEqual(
            mock_post.call_args.kwargs["json"]["repositories"],
            ["app", "service", "bare"],
        )

    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_full_path_and_bare_name_share_one_cache_entry(self, mock_post, _mock_jwt):
        """They normalize to the same scope, so minting twice would be waste."""
        mock_post.return_value = _mock_token_response()

        first = github_app.get_installation_token(42, repositories=["acme/app"])
        second = github_app.get_installation_token(42, repositories=["app"])

        self.assertEqual(first, second)
        mock_post.assert_called_once()

    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "post")
    def test_unscoped_request_sends_no_repositories_key(self, mock_post, _mock_jwt):
        mock_post.return_value = _mock_token_response()

        github_app.get_installation_token(42)

        self.assertNotIn("repositories", mock_post.call_args.kwargs["json"])


class TestGetInstallation(SimpleTestCase):
    @mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
    @mock.patch.object(github_app.requests, "get")
    def test_returns_json(self, mock_get, _mock_jwt):
        resp = mock.Mock()
        resp.raise_for_status = mock.Mock()
        resp.json.return_value = {
            "id": 42,
            "account": {"login": "acme", "type": "Organization"},
        }
        mock_get.return_value = resp

        result = github_app.get_installation(42)

        self.assertEqual(result["account"]["login"], "acme")
        mock_get.assert_called_once()
        self.assertIn("/app/installations/42", mock_get.call_args[0][0])
