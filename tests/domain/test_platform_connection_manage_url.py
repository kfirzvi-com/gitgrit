"""Unit tests for PlatformConnection.github_app_manage_url — the read-only
deep-link surfaced in the settings connections table for App connections."""
import pytest
from model_bakery import baker

from app.domain.models import AuthMethod


@pytest.mark.django_db
def test_manage_url_for_organization_installation():
    conn = baker.make(
        "app.PlatformConnection",
        platform="github",
        auth_method=AuthMethod.GITHUB_APP,
        installation_id=555,
        account_login="acme",
        account_type="Organization",
    )
    assert conn.github_app_manage_url == (
        "https://github.com/organizations/acme/settings/installations/555"
    )


@pytest.mark.django_db
def test_manage_url_for_user_installation():
    conn = baker.make(
        "app.PlatformConnection",
        platform="github",
        auth_method=AuthMethod.GITHUB_APP,
        installation_id=999,
        account_login="octocat",
        account_type="User",
    )
    assert conn.github_app_manage_url == (
        "https://github.com/settings/installations/999"
    )


@pytest.mark.django_db
def test_manage_url_none_for_pat_connection():
    conn = baker.make(
        "app.PlatformConnection",
        platform="github",
        auth_method=AuthMethod.PAT,
        access_token="ghp_stored",
    )
    assert conn.github_app_manage_url is None


@pytest.mark.django_db
def test_manage_url_none_when_installation_id_missing():
    conn = baker.make(
        "app.PlatformConnection",
        platform="github",
        auth_method=AuthMethod.GITHUB_APP,
        installation_id=None,
        account_login="acme",
        account_type="Organization",
    )
    assert conn.github_app_manage_url is None
