"""``resolve_llm_roles`` hands the sandbox only LiteLLM-shaped providers.

A "TypeSafe (Jev)" provider is the architecture map's, never a role's: the
settings view refuses to create such a role, and this is the second guard so
a row that got there anyway (admin, old data) is not handed to a standard as
``typesafe/...``, which LiteLLM cannot call.
"""
from django.test import TestCase
from model_bakery import baker

from app.application.standard_engine import resolve_llm_roles
from app.domain.models import LLMRole


class ResolveLLMRolesTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def _provider(self, provider_type, **kw):
        defaults = dict(
            tenant=self.tenant,
            provider_type=provider_type,
            api_key=f"{provider_type}-key",
            enabled=True,
        )
        defaults.update(kw)
        return baker.make("app.LLMProvider", **defaults)

    def test_roles_resolve_to_litellm_model_strings(self):
        anthropic = self._provider("anthropic", base_url="")
        LLMRole.objects.create(
            tenant=self.tenant, name="reasoning", provider=anthropic, model="claude-opus-4"
        )
        self.assertEqual(
            resolve_llm_roles(self.tenant),
            {"reasoning": {"model": "anthropic/claude-opus-4", "base_url": "", "api_key": "anthropic-key"}},
        )

    def test_typesafe_role_is_excluded(self):
        anthropic = self._provider("anthropic")
        typesafe = self._provider("typesafe")
        LLMRole.objects.create(
            tenant=self.tenant, name="reasoning", provider=anthropic, model="claude-opus-4"
        )
        LLMRole.objects.create(
            tenant=self.tenant, name="code", provider=typesafe, model="jev-1.13.0"
        )
        self.assertEqual(list(resolve_llm_roles(self.tenant)), ["reasoning"])

    def test_disabled_provider_is_excluded(self):
        off = self._provider("openai", enabled=False)
        LLMRole.objects.create(tenant=self.tenant, name="code", provider=off, model="gpt-5")
        self.assertEqual(resolve_llm_roles(self.tenant), {})
