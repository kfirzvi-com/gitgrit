"""The signed GitHub App install-initiation view."""
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.presentation.views.github_app_views import INSTALL_STATE_SALT


def _login(client, role="owner"):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role=role)
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


@pytest.mark.django_db
@override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_SLUG="gitgrit-app")
class TestGitHubAppInstall(TestCase):
    def test_redirects_to_github_with_signed_state(self):
        user, tenant = _login(self.client)
        resp = self.client.get(reverse("github_app_install"))
        assert resp.status_code == 302

        parsed = urlparse(resp["Location"])
        assert parsed.scheme == "https"
        assert parsed.netloc == "github.com"
        assert parsed.path == "/apps/gitgrit-app/installations/new"

        state = parse_qs(parsed.query)["state"][0]
        payload = signing.loads(state, salt=INSTALL_STATE_SALT)
        assert payload["tenant_id"] == str(tenant.id)
        assert payload["user_id"] == str(user.id)
        assert payload["nonce"]

    def test_member_without_admin_is_denied(self):
        _login(self.client, role="member")
        resp = self.client.get(reverse("github_app_install"))
        # Bounced back to settings, no GitHub redirect.
        assert resp.status_code == 302
        assert "github.com" not in resp["Location"]


@pytest.mark.django_db
@override_settings(GITHUB_APP_ENABLED=False)
class TestGitHubAppInstallDisabled(TestCase):
    def test_flag_off_is_404(self):
        _login(self.client)
        resp = self.client.get(reverse("github_app_install"))
        assert resp.status_code == 404
