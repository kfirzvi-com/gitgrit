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
from app.infrastructure.llm_models import Discovery, ProbeResult


def _found(models, results=()):
    return Discovery(list(models), list(results))

ADD_URL = "/tenants/llm/providers/add/"
DISCOVER = "app.presentation.views.tenant_views.discover"


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


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestSetLLMRoleHtmx(TestCase):
    URL = "/tenants/llm/roles/reasoning/set/"

    def _login(self, role="admin"):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role=role)
        self.client.force_login(user)
        provider = baker.make(
            "app.LLMProvider",
            tenant=tenant,
            provider_type="anthropic",
            display_name="Anthropic",
            available_models=["m1", "m2"],
            enabled=True,
        )
        return tenant, provider

    def test_save_returns_the_form_with_a_success_message(self):
        tenant, provider = self._login()
        resp = self.client.post(
            self.URL,
            {"provider_id": str(provider.id), "model": "m1"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'id="llm-role-reasoning"' in body
        assert "Role &quot;reasoning&quot; set to Anthropic/m1." in body
        assert 'data-current-model="m1"' in body
        assert "<html" not in body
        role = LLMRole.objects.get(tenant=tenant, name="reasoning")
        assert (role.provider_id, role.model) == (provider.id, "m1")

    def test_missing_model_shows_the_error_inline_and_saves_nothing(self):
        tenant, provider = self._login()
        resp = self.client.post(
            self.URL, {"provider_id": str(provider.id), "model": ""},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert "Select a model for the role." in resp.content.decode()
        assert not LLMRole.objects.filter(tenant=tenant).exists()

    def test_clearing_returns_the_form_with_a_message(self):
        tenant, provider = self._login()
        LLMRole.objects.create(
            tenant=tenant, name="reasoning", provider=provider, model="m1"
        )
        resp = self.client.post(
            self.URL, {"provider_id": ""}, HTTP_HX_REQUEST="true"
        )
        assert resp.status_code == 200
        assert "Cleared the" in resp.content.decode()
        assert not LLMRole.objects.filter(tenant=tenant).exists()

    def test_member_gets_an_inline_error_not_a_redirect(self):
        tenant, provider = self._login(role="member")
        resp = self.client.post(
            self.URL,
            {"provider_id": str(provider.id), "model": "m1"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert "permission" in resp.content.decode()
        assert not LLMRole.objects.filter(tenant=tenant).exists()

    def test_without_htmx_it_still_redirects(self):
        tenant, provider = self._login()
        resp = self.client.post(
            self.URL, {"provider_id": str(provider.id), "model": "m1"}
        )
        assert resp.status_code == 302
        assert LLMRole.objects.filter(tenant=tenant, name="reasoning").exists()


@pytest.mark.django_db
class TestProviderFormsHtmx(TestCase):
    def _login(self, role="admin"):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role=role)
        self.client.force_login(user)
        provider = baker.make(
            "app.LLMProvider",
            tenant=tenant,
            provider_type="anthropic",
            display_name="Anthropic",
            available_models=["m1"],
            api_key="sk-old",
            enabled=True,
        )
        return tenant, provider

    def _edit_url(self, provider):
        return f"/tenants/llm/providers/{provider.id}/edit/"

    # --- add ---------------------------------------------------------------

    def test_add_returns_partial_with_table_roles_and_message(self):
        tenant, _ = self._login()
        with patch(DISCOVER, return_value=_found(["x1", "x2"])):
            resp = self.client.post(
                ADD_URL,
                {"provider_type": "openai", "display_name": "Mine", "api_key": "sk-new"},
                HTTP_HX_REQUEST="true",
            )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "<html" not in body
        assert "added — 2 models" in body
        assert 'id="llm-providers-table"' in body and "Mine" in body
        assert 'id="llm-role-reasoning"' in body
        assert 'id="llm-models-map"' in body and "x1" in body
        assert "hx-swap-oob" in body
        assert "sk-new" not in body
        assert LLMProvider.objects.filter(tenant=tenant, display_name="Mine").exists()

    def test_add_validation_error_is_inline_and_saves_nothing(self):
        tenant, _ = self._login()
        with patch(DISCOVER, return_value=_found([])):
            resp = self.client.post(
                ADD_URL, {"provider_type": "openai", "api_key": ""},
                HTTP_HX_REQUEST="true",
            )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "API key is required." in body
        assert "llm-providers-table" not in body
        assert LLMProvider.objects.filter(tenant=tenant).count() == 1

    def test_add_invalid_type_is_inline(self):
        self._login()
        resp = self.client.post(
            ADD_URL, {"provider_type": "bogus", "api_key": "k"}, HTTP_HX_REQUEST="true"
        )
        assert resp.status_code == 200
        assert "Invalid provider type." in resp.content.decode()

    def test_add_member_gets_inline_error_not_a_redirect(self):
        tenant, _ = self._login(role="member")
        resp = self.client.post(
            ADD_URL, {"provider_type": "openai", "api_key": "k"}, HTTP_HX_REQUEST="true"
        )
        assert resp.status_code == 200
        assert "permission" in resp.content.decode()
        assert LLMProvider.objects.filter(tenant=tenant).count() == 1

    def test_add_without_htmx_still_redirects(self):
        tenant, _ = self._login()
        with patch(DISCOVER, return_value=_found(["x1"])):
            resp = self.client.post(ADD_URL, {"provider_type": "openai", "api_key": "k"})
        assert resp.status_code == 302
        assert LLMProvider.objects.filter(tenant=tenant).count() == 2

    # --- edit --------------------------------------------------------------

    def test_edit_returns_partial_closes_modal_and_keeps_key_when_blank(self):
        tenant, provider = self._login()
        resp = self.client.post(
            self._edit_url(provider),
            {"display_name": "Renamed", "base_url": "", "api_key": "", "models": "a, b"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "<html" not in body
        assert "Provider &quot;Renamed&quot; updated." in body
        assert 'id="llm-providers-table"' in body and "Renamed" in body
        assert 'id="llm-role-reasoning"' in body
        assert "edit-provider-modal" in body and ".close()" in body
        provider.refresh_from_db()
        assert provider.display_name == "Renamed"
        assert provider.available_models == ["a", "b"]
        assert provider.api_key == "sk-old"

    def test_edit_replaces_key_when_given_and_never_echoes_it(self):
        _, provider = self._login()
        resp = self.client.post(
            self._edit_url(provider),
            {"display_name": "", "api_key": "sk-fresh"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert "sk-fresh" not in resp.content.decode()
        provider.refresh_from_db()
        assert provider.api_key == "sk-fresh"

    def test_edit_member_gets_inline_error_and_changes_nothing(self):
        _, provider = self._login(role="member")
        resp = self.client.post(
            self._edit_url(provider), {"display_name": "Hacked"}, HTTP_HX_REQUEST="true"
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "permission" in body
        assert ".close()" not in body
        provider.refresh_from_db()
        assert provider.display_name == "Anthropic"

    def test_edit_other_workspace_provider_is_404(self):
        self._login()
        other = baker.make("app.LLMProvider", tenant=baker.make("app.Tenant"))
        resp = self.client.post(
            self._edit_url(other), {"display_name": "x"}, HTTP_HX_REQUEST="true"
        )
        assert resp.status_code == 404

    def test_edit_without_htmx_still_redirects(self):
        _, provider = self._login()
        resp = self.client.post(self._edit_url(provider), {"display_name": "Plain"})
        assert resp.status_code == 302
        provider.refresh_from_db()
        assert provider.display_name == "Plain"

    @override_settings(STORAGES=NON_MANIFEST_STORAGES)
    def test_settings_page_wires_both_forms_to_htmx(self):
        self._login()
        body = self.client.get("/tenants/settings/").content.decode()
        assert 'id="add-provider-form"' in body and "hx-post" in body
        assert 'id="edit-provider-feedback"' in body
        assert 'id="llm-providers-table"' in body
        assert 'id="llm-roles-list"' in body
