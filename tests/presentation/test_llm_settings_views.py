"""View tests for the LLM provider/role workspace settings screens."""
import re
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

    def test_role_row_shows_last_error(self):
        _, tenant = self._admin()
        provider = self._provider(tenant)
        baker.make(
            "app.LLMRole", tenant=tenant, name="reasoning", provider=provider,
            model="claude-opus-4",
            last_error="NotFoundError: This model is no longer available to new users.",
        )
        resp = self.client.get("/tenants/settings/")
        assert resp.status_code == 200
        assert b'data-role-error="reasoning"' in resp.content
        assert b"no longer available to new users" in resp.content
        # Same model still in the provider's list: only the runtime error shows.
        assert b'data-role-warning="reasoning"' not in resp.content

    def test_role_row_warns_when_model_left_the_provider_list(self):
        _, tenant = self._admin()
        provider = self._provider(tenant, available_models=["claude-opus-5"])
        baker.make(
            "app.LLMRole", tenant=tenant, name="reasoning", provider=provider,
            model="claude-opus-4",
        )
        resp = self.client.get("/tenants/settings/")
        assert b'data-role-warning="reasoning"' in resp.content
        assert b'data-role-error="reasoning"' not in resp.content

    def test_healthy_role_row_shows_no_alerts(self):
        _, tenant = self._admin()
        provider = self._provider(tenant)
        baker.make(
            "app.LLMRole", tenant=tenant, name="reasoning", provider=provider,
            model="claude-opus-4",
        )
        resp = self.client.get("/tenants/settings/")
        assert b"data-role-warning=" not in resp.content
        assert b"data-role-error=" not in resp.content


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

    def test_set_role_clears_recorded_error(self):
        _, tenant = self._admin()
        provider = self._provider(tenant)
        baker.make(
            "app.LLMRole", tenant=tenant, name="reasoning", provider=provider,
            model="m1", last_error="model retired",
        )
        self.client.post(
            "/tenants/llm/roles/reasoning/set/",
            {"provider_id": str(provider.id), "model": "m2"},
        )
        role = LLMRole.objects.get(tenant=tenant, name="reasoning")
        assert role.model == "m2"
        assert role.last_error == ""
        assert role.last_error_at is None

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
class TestProviderFailureReachesSettingsPage(TestCase):
    """End to end: a provider rejecting the mapping run must show up, as a
    plain sentence, where an admin fixes it. Before this existed the only
    trace was Project.deps_error, which nothing rendered."""

    GEMINI_429 = (
        "litellm.RateLimitError: litellm.RateLimitError: GeminiException - {"
        '"error": {"code": 429, "message": "Your prepayment credits are depleted. '
        'Please go to AI Studio at https://ai.studio/projects to manage your project.", '
        '"status": "RESOURCE_EXHAUSTED"}}'
    )

    def test_failed_mapping_run_is_explained_under_the_role(self):
        from types import SimpleNamespace

        from app.application import dependency_agent as da

        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="admin")
        provider = baker.make(
            "app.LLMProvider", tenant=tenant, provider_type="gemini",
            available_models=["gemini-3.1-pro-preview"],
        )
        baker.make(
            "app.LLMRole", tenant=tenant, name="reasoning", provider=provider,
            model="gemini-3.1-pro-preview",
        )
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        project = baker.make("app.Project", tenant=tenant, platform_connection=conn)

        def rejected(self, **kw):
            raise RuntimeError(TestProviderFailureReachesSettingsPage.GEMINI_429)

        with (
            patch.object(da.LLMAgent, "run", rejected),
            patch.object(da, "get_platform_client", lambda c: SimpleNamespace()),
            patch.object(
                da, "resolve_llm_roles",
                lambda t: {"reasoning": {"model": "gemini/x", "base_url": "", "api_key": "k"}},
            ),
        ):
            with self.assertRaises(RuntimeError):
                da.infer_and_store(project)

        self.client.force_login(user)
        resp = self.client.get("/tenants/settings/")
        html = resp.content.decode()

        assert resp.status_code == 200
        alert = re.search(
            r'<div class="alert alert-error[^"]*"[^>]*data-role-error="reasoning">(.*?)</div>',
            html, re.S,
        )
        assert alert, "no error alert rendered under the reasoning role"
        alert_text = alert.group(1)
        assert "Your prepayment credits are depleted." in alert_text
        # The provider's follow-up sentence and the LiteLLM/JSON wrapping stay out.
        assert "AI Studio" not in alert_text
        assert "litellm" not in alert_text
        assert "RESOURCE_EXHAUSTED" not in alert_text
