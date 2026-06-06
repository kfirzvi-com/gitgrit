"""View tests for the LLM provider/role workspace settings screens."""
from unittest.mock import patch

import pytest
from django.test import TestCase, override_settings
from model_bakery import baker

# Render full pages without the manifest static storage (no collectstatic in tests).
NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

from app.domain.models import LLMProvider, LLMRole

ADD_URL = "/tenants/llm/providers/add/"
DISCOVER = "app.presentation.views.tenant_views.discover_models"


@pytest.mark.django_db
class TestLLMProviderViews(TestCase):
    def _admin(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="admin")
        self.client.force_login(user)
        return user, tenant

    def _member(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        self.client.force_login(user)
        return user, tenant

    def _provider(self, tenant, **kw):
        defaults = dict(
            tenant=tenant,
            provider_type="anthropic",
            display_name="Anthropic",
            available_models=["claude-opus-4"],
            enabled=True,
        )
        defaults.update(kw)
        return baker.make("app.LLMProvider", **defaults)

    def test_anonymous_redirects(self):
        resp = self.client.post(ADD_URL, {"provider_type": "anthropic", "api_key": "k"})
        assert resp.status_code == 302
        assert LLMProvider.objects.count() == 0

    def test_member_forbidden(self):
        self._member()
        resp = self.client.post(ADD_URL, {"provider_type": "anthropic", "api_key": "k"})
        assert resp.status_code == 302
        assert LLMProvider.objects.count() == 0

    def test_admin_adds_provider_with_discovered_models(self):
        self._admin()
        with patch(DISCOVER, return_value=["claude-opus-4", "claude-sonnet-4"]):
            resp = self.client.post(
                ADD_URL,
                {"provider_type": "anthropic", "display_name": "A", "api_key": "sk-x"},
            )
        assert resp.status_code == 302
        provider = LLMProvider.objects.get()
        assert provider.display_name == "A"
        assert provider.provider_type == "anthropic"
        assert provider.available_models == ["claude-opus-4", "claude-sonnet-4"]

    def test_add_requires_api_key(self):
        self._admin()
        with patch(DISCOVER, return_value=[]):
            resp = self.client.post(ADD_URL, {"provider_type": "anthropic", "api_key": ""})
        assert resp.status_code == 302
        assert LLMProvider.objects.count() == 0

    def test_add_rejects_invalid_type(self):
        self._admin()
        with patch(DISCOVER, return_value=[]):
            resp = self.client.post(ADD_URL, {"provider_type": "bogus", "api_key": "k"})
        assert resp.status_code == 302
        assert LLMProvider.objects.count() == 0

    def test_remove_provider_cascades_roles(self):
        _, tenant = self._admin()
        provider = self._provider(tenant)
        LLMRole.objects.create(
            tenant=tenant, name="reasoning", provider=provider, model="claude-opus-4"
        )
        resp = self.client.post(
            f"/tenants/llm/providers/{provider.id}/remove/"
        )
        assert resp.status_code == 302
        assert LLMProvider.objects.count() == 0
        assert LLMRole.objects.count() == 0

    @override_settings(STORAGES=NON_MANIFEST_STORAGES)
    def test_settings_page_renders_llm_sections(self):
        _, tenant = self._admin()
        self._provider(tenant)
        resp = self.client.get("/tenants/settings/")
        assert resp.status_code == 200
        assert b"LLM Providers" in resp.content
        assert b"LLM Roles" in resp.content


@pytest.mark.django_db
class TestSetLLMRole(TestCase):
    def _admin(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="admin")
        self.client.force_login(user)
        return user, tenant

    def _provider(self, tenant, name="Anthropic"):
        return baker.make(
            "app.LLMProvider",
            tenant=tenant,
            provider_type="anthropic",
            display_name=name,
            available_models=["m1", "m2"],
            enabled=True,
        )

    def test_set_role_creates_assignment(self):
        _, tenant = self._admin()
        provider = self._provider(tenant)
        resp = self.client.post(
            "/tenants/llm/roles/reasoning/set/",
            {"provider_id": str(provider.id), "model": "m1"},
        )
        assert resp.status_code == 302
        role = LLMRole.objects.get(tenant=tenant, name="reasoning")
        assert role.provider_id == provider.id
        assert role.model == "m1"

    def test_set_role_is_idempotent_per_tenant_and_name(self):
        _, tenant = self._admin()
        p1 = self._provider(tenant, name="P1")
        p2 = self._provider(tenant, name="P2")
        self.client.post(
            "/tenants/llm/roles/reasoning/set/",
            {"provider_id": str(p1.id), "model": "m1"},
        )
        self.client.post(
            "/tenants/llm/roles/reasoning/set/",
            {"provider_id": str(p2.id), "model": "m2"},
        )
        roles = LLMRole.objects.filter(tenant=tenant, name="reasoning")
        assert roles.count() == 1
        assert roles.first().provider_id == p2.id

    def test_clearing_role_deletes_it(self):
        _, tenant = self._admin()
        provider = self._provider(tenant)
        LLMRole.objects.create(
            tenant=tenant, name="reasoning", provider=provider, model="m1"
        )
        resp = self.client.post(
            "/tenants/llm/roles/reasoning/set/", {"provider_id": ""}
        )
        assert resp.status_code == 302
        assert LLMRole.objects.filter(tenant=tenant, name="reasoning").count() == 0

    def test_invalid_role_name_rejected(self):
        _, tenant = self._admin()
        provider = self._provider(tenant)
        resp = self.client.post(
            "/tenants/llm/roles/bogus/set/",
            {"provider_id": str(provider.id), "model": "m1"},
        )
        assert resp.status_code == 302
        assert LLMRole.objects.count() == 0
