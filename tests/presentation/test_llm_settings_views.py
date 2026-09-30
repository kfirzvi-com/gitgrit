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
from app.infrastructure.jev import JevError
from app.infrastructure.llm_models import Discovery, ProbeResult


def _found(models, results=()):
    return Discovery(list(models), list(results))

ADD_URL = "/tenants/llm/providers/add/"
DISCOVER = "app.presentation.views.tenant_views.discover"
PING = "app.infrastructure.jev.JevClient.ping"


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
        with patch(DISCOVER, return_value=_found(["claude-opus-4", "claude-sonnet-4"])):
            resp = self.client.post(
                ADD_URL,
                {"provider_type": "anthropic", "display_name": "A", "api_key": "sk-x"},
            )
        assert resp.status_code == 302
        provider = LLMProvider.objects.get()
        assert provider.display_name == "A"
        assert provider.provider_type == "anthropic"
        assert provider.available_models == ["claude-opus-4", "claude-sonnet-4"]

    def test_add_with_no_usable_models_explains_why(self):
        self._admin()
        body = (
            'GeminiException - { "error": { "code": 402, "message": "Your prepayment '
            'credits are depleted. Please go to AI Studio." } }'
        )
        found = _found([], [ProbeResult("gemini-3.5-flash", False, 402, body)])
        with patch(DISCOVER, return_value=found):
            resp = self.client.post(
                ADD_URL, {"provider_type": "gemini", "api_key": "g"}, follow=True
            )
        assert LLMProvider.objects.get().available_models == []
        assert "Your prepayment credits are depleted" in resp.content.decode()

    def test_add_requires_api_key(self):
        self._admin()
        with patch(DISCOVER, return_value=_found([])):
            resp = self.client.post(ADD_URL, {"provider_type": "anthropic", "api_key": ""})
        assert resp.status_code == 302
        assert LLMProvider.objects.count() == 0

    def test_add_rejects_invalid_type(self):
        self._admin()
        with patch(DISCOVER, return_value=_found([])):
            resp = self.client.post(ADD_URL, {"provider_type": "bogus", "api_key": "k"})
        assert resp.status_code == 302
        assert LLMProvider.objects.count() == 0

    def test_admin_adds_typesafe_provider_with_its_one_model(self):
        self._admin()
        with patch(DISCOVER, return_value=_found(["jev-1.13.0"])):
            resp = self.client.post(
                ADD_URL, {"provider_type": "typesafe", "api_key": "ts-key"}
            )
        assert resp.status_code == 302
        provider = LLMProvider.objects.get()
        assert provider.provider_type == "typesafe"
        assert provider.display_name == "TypeSafe (Jev)"
        assert provider.available_models == ["jev-1.13.0"]
        assert provider.api_key == "ts-key"

    def test_typesafe_connection_test_pings_jev(self):
        _, tenant = self._admin()
        provider = self._provider(
            tenant, provider_type="typesafe", display_name="TypeSafe (Jev)"
        )
        with patch(PING, return_value=None) as ping:
            resp = self.client.post(f"/tenants/llm/providers/{provider.id}/test/")
        assert b"Connected" in resp.content
        assert ping.call_count == 1
        with patch(PING, side_effect=JevError("401 bad key")):
            resp = self.client.post(f"/tenants/llm/providers/{provider.id}/test/")
        assert b"Failed" in resp.content

    def test_typesafe_test_and_fetch_use_the_stored_model(self):
        _, tenant = self._admin()
        provider = self._provider(
            tenant, provider_type="typesafe", display_name="TypeSafe (Jev)",
            available_models=["jev-2.0.0"],
        )
        with patch("app.presentation.views.tenant_views.test_provider", return_value=True) as tp:
            self.client.post(f"/tenants/llm/providers/{provider.id}/test/")
        assert tp.call_args.kwargs["model"] == "jev-2.0.0"
        with patch(DISCOVER, return_value=_found(["jev-2.0.0"])) as dc:
            self.client.post(f"/tenants/llm/providers/{provider.id}/fetch-models/")
        assert dc.call_args.kwargs["model"] == "jev-2.0.0"

    @override_settings(STORAGES=NON_MANIFEST_STORAGES)
    def test_role_dropdown_omits_typesafe_provider(self):
        _, tenant = self._admin()
        anthropic = self._provider(tenant)
        typesafe = self._provider(
            tenant, provider_type="typesafe", display_name="TypeSafe (Jev)"
        )
        resp = self.client.get("/tenants/settings/")
        html = resp.content.decode()
        assert f'<option value="{anthropic.id}"' in html
        assert f'<option value="{typesafe.id}"' not in html
        assert "TypeSafe (Jev)" in html  # still listed in the providers table

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

    def test_typesafe_provider_cannot_take_a_role(self):
        _, tenant = self._admin()
        provider = baker.make(
            "app.LLMProvider",
            tenant=tenant,
            provider_type="typesafe",
            display_name="TypeSafe (Jev)",
            available_models=["jev-1.13.0"],
            enabled=True,
        )
        resp = self.client.post(
            "/tenants/llm/roles/reasoning/set/",
            {"provider_id": str(provider.id), "model": "jev-1.13.0"},
            follow=True,
        )
        assert "TypeSafe is used by the architecture map, not by roles." in resp.content.decode()
        assert LLMRole.objects.count() == 0

    def test_invalid_role_name_rejected(self):
        _, tenant = self._admin()
        provider = self._provider(tenant)
        resp = self.client.post(
            "/tenants/llm/roles/bogus/set/",
            {"provider_id": str(provider.id), "model": "m1"},
        )
        assert resp.status_code == 302
        assert LLMRole.objects.count() == 0
