"""The Add Connection card on workspace settings.

Connection setup uses the same flat inline-card form as Add LLM Provider: a
platform select plus token fields, with the flag-gated GitHub App install as a
secondary action. Also covers the connections-table Method column and the
per-row 'Manage on GitHub' link."""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AuthMethod

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
class TestAddConnectionCard(TestCase):
    @override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_SLUG="gitgrit-app")
    def test_card_renders_flat_form_for_admin(self):
        _login_owner(self.client)
        resp = self.client.get(reverse("tenant_settings"))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'id="add-connection-card"' in body
        assert 'id="platform-select"' in body
        assert reverse("add_connection") in body

    @override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_SLUG="gitgrit-app")
    def test_modal_wizard_is_gone(self):
        _login_owner(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert 'id="add-connection-modal"' not in body
        assert 'id="add-conn-method-row"' not in body

    @override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_SLUG="gitgrit-app")
    def test_install_button_shown_when_flag_enabled(self):
        _login_owner(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert "Install GitHub App" in body
        assert reverse("github_app_install") in body

    @override_settings(GITHUB_APP_ENABLED=False)
    def test_install_button_hidden_when_flag_disabled(self):
        _login_owner(self.client)
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert "Install GitHub App" not in body
        assert reverse("github_app_install") not in body
        # The token form is unaffected by the flag.
        assert 'id="add-connection-card"' in body

    def test_card_hidden_for_non_admin(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert 'id="add-connection-card"' not in body

    @override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_SLUG="gitgrit-app")
    def test_method_column_and_manage_link_visibility(self):
        _, tenant = _login_owner(self.client)
        baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=AuthMethod.PAT,
            access_token="ghp_pat",
            display_name="PAT conn",
        )
        baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=42,
            account_login="acme",
            account_type="Organization",
            display_name="App conn",
        )
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert "<th>Method</th>" in body
        assert "Manage on GitHub" in body
        assert (
            "https://github.com/organizations/acme/settings/installations/42"
            in body
        )

    @override_settings(GITHUB_APP_ENABLED=True, GITHUB_APP_SLUG="gitgrit-app")
    def test_manage_link_absent_for_pat_only(self):
        _, tenant = _login_owner(self.client)
        baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            auth_method=AuthMethod.PAT,
            access_token="ghp_pat",
            display_name="PAT conn",
        )
        body = self.client.get(reverse("tenant_settings")).content.decode()
        assert "Manage on GitHub" not in body
        # PAT rows keep the Edit Token action.
        assert "Edit Token" in body
