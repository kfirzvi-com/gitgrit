"""Unit tests for PlatformConnection.get_access_token — the auth-method seam.

PAT connections return the stored token verbatim; GitHub App connections mint a
short-lived installation token (mocked here, since no real App exists yet).
"""
from unittest import mock

import pytest
from model_bakery import baker

from app.domain.models import AuthMethod


@pytest.mark.django_db
def test_pat_connection_returns_stored_token():
    conn = baker.make(
        "app.PlatformConnection",
        platform="github",
        auth_method=AuthMethod.PAT,
        access_token="ghp_stored_pat",
    )
    assert conn.get_access_token() == "ghp_stored_pat"


@pytest.mark.django_db
def test_github_app_connection_mints_installation_token():
    conn = baker.make(
        "app.PlatformConnection",
        platform="github",
        auth_method=AuthMethod.GITHUB_APP,
        access_token=None,
        installation_id=777,
    )
    with mock.patch(
        "app.infrastructure.github_app.get_installation_token",
        return_value="ghs_minted",
    ) as mock_mint:
        token = conn.get_access_token(repositories=["acme/app"])

    assert token == "ghs_minted"
    mock_mint.assert_called_once_with(777, ["acme/app"])
