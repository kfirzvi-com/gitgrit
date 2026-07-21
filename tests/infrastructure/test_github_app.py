"""Unit tests for the GitHub App installation-token minting service.

No real GitHub App exists yet, so every HTTP exchange is mocked. These tests
pin: (1) the App JWT is a valid RS256 token with the expected claims, (2) an
installation token is returned, and (3) a second call within the token's TTL is
served from cache without a second HTTP request.
"""
from __future__ import annotations

import time
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings

from app.infrastructure import github_app


def _generate_private_key_pem() -> tuple[str, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


@pytest.fixture(autouse=True)
def _clear_cache():
    github_app._token_cache.clear()
    yield
    github_app._token_cache.clear()


def test_build_app_jwt_is_valid_rs256_with_expected_claims():
    pem, public_key = _generate_private_key_pem()
    with override_settings(GITHUB_APP_ID="123456", GITHUB_APP_PRIVATE_KEY=pem):
        token = github_app.build_app_jwt()

    decoded = jwt.decode(token, public_key, algorithms=["RS256"])
    assert decoded["iss"] == "123456"
    # GitHub caps the App JWT lifetime at 10 minutes.
    assert decoded["exp"] - decoded["iat"] <= 600


def _mock_token_response(expires_in_seconds: int = 3600, token: str = "ghs_installtoken"):
    expires_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in_seconds)
    )
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = {"token": token, "expires_at": expires_at}
    return resp


@mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
@mock.patch.object(github_app.requests, "post")
def test_get_installation_token_returns_token(mock_post, _mock_jwt):
    mock_post.return_value = _mock_token_response()
    token = github_app.get_installation_token(42)
    assert token == "ghs_installtoken"
    mock_post.assert_called_once()


@mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
@mock.patch.object(github_app.requests, "post")
def test_second_call_within_ttl_is_a_cache_hit(mock_post, _mock_jwt):
    mock_post.return_value = _mock_token_response()
    first = github_app.get_installation_token(42)
    second = github_app.get_installation_token(42)
    assert first == second == "ghs_installtoken"
    # Cached: no second HTTP request.
    mock_post.assert_called_once()


@mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
@mock.patch.object(github_app.requests, "post")
def test_different_repo_scope_mints_a_separate_token(mock_post, _mock_jwt):
    mock_post.side_effect = [
        _mock_token_response(token="tok-all"),
        _mock_token_response(token="tok-scoped"),
    ]
    all_token = github_app.get_installation_token(42)
    scoped_token = github_app.get_installation_token(42, repositories=["acme/app"])
    assert all_token == "tok-all"
    assert scoped_token == "tok-scoped"
    assert mock_post.call_count == 2


@mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
@mock.patch.object(github_app.requests, "post")
def test_expired_cached_token_is_refetched(mock_post, _mock_jwt):
    # First token already past its safety buffer, so the next call must refetch.
    mock_post.side_effect = [
        _mock_token_response(expires_in_seconds=30, token="tok-old"),
        _mock_token_response(token="tok-new"),
    ]
    first = github_app.get_installation_token(42)
    second = github_app.get_installation_token(42)
    assert first == "tok-old"
    assert second == "tok-new"
    assert mock_post.call_count == 2


@mock.patch.object(github_app, "build_app_jwt", return_value="fake.jwt")
@mock.patch.object(github_app.requests, "get")
def test_get_installation_returns_json(mock_get, _mock_jwt):
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json.return_value = {"id": 42, "account": {"login": "acme", "type": "Organization"}}
    mock_get.return_value = resp

    result = github_app.get_installation(42)
    assert result["account"]["login"] == "acme"
    mock_get.assert_called_once()
    assert "/app/installations/42" in mock_get.call_args[0][0]
