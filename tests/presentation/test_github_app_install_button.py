"""The minimal 'Install GitHub App' entry point on workspace settings, gated on
the GITHUB_APP_ENABLED feature flag."""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _login_owner(client):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestInstallButton(TestCase):
    @override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_SLUG="gitgrit-app")
    def test_button_shown_when_flag_enabled(self):
        _login_owner(self.client)
        resp = self.client.get(reverse("tenant_settings"))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Install GitHub App" in body
        assert reverse("github_app_install") in body

    @override_settings(GITHUB_APP_ENABLED=False)
    def test_button_hidden_when_flag_disabled(self):
        _login_owner(self.client)
        resp = self.client.get(reverse("tenant_settings"))
        assert resp.status_code == 200
        assert "Install GitHub App" not in resp.content.decode()
