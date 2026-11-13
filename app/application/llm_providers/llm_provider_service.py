from __future__ import annotations

import re

from app.application.errors import NotFoundError
from app.application.llm_providers.llm_provider_error import LLMProviderError
from app.domain.models import LLMProvider, LLMProviderType, LLMRole
from app.infrastructure.llm_models import discover, test_provider


class LLMProviderService:
    """Adding, changing and removing a workspace's LLM providers, and setting
    its roles. Who may do this is the caller's check (workspace owners and
    admins)."""

    @classmethod
    def add(cls, tenant, *, provider_type: str, api_key: str, display_name: str = "",
            base_url: str = "") -> tuple[LLMProvider, str]:
        """Add a provider with the models its key can use (discovered).
        Returns it and, when no model was found, the provider's own reason
        ("" when it gave none)."""
        if provider_type not in LLMProviderType.values:
            raise LLMProviderError(
                f"Unknown provider type {provider_type!r}; one of: {', '.join(LLMProviderType.values)}."
            )
        api_key = (api_key or "").strip()
        if not api_key:
            raise LLMProviderError("API key is required.")
        base_url = (base_url or "").strip()
        found = discover(provider_type, base_url, api_key)
        provider = LLMProvider.objects.create(
            tenant=tenant,
            provider_type=provider_type,
            display_name=(display_name or "").strip() or cls.auto_name(tenant, provider_type),
            base_url=base_url,
            api_key=api_key,
            available_models=found.models,
        )
        return provider, ("" if found.models else found.reason or "")

    @staticmethod
    def edit(provider: LLMProvider, *, display_name=None, base_url=None, api_key=None, models=None) -> LLMProvider:
        """Change what is passed; None leaves a field as it is. A blank name
        or key is ignored (a key is never shown, so blank means keep it);
        ``models`` replaces the list when it names any."""
        if display_name and display_name.strip():
            provider.display_name = display_name.strip()
        if base_url is not None:
            provider.base_url = base_url.strip()
        if api_key and api_key.strip():
            provider.api_key = api_key.strip()
        if models is not None:
            names = models if isinstance(models, (list, tuple)) else re.split(r"[\n,]", models)
            names = [m.strip() for m in names if m and m.strip()]
            if names:
                provider.available_models = names
        provider.save()
        return provider

    @staticmethod
    def remove(provider: LLMProvider) -> None:
        provider.delete()  # cascades to any roles pointing at it

    @staticmethod
    def test(provider: LLMProvider) -> bool:
        """True when the provider accepts the key."""
        return test_provider(provider.provider_type, provider.base_url, provider.api_key)

    @staticmethod
    def refresh_models(provider: LLMProvider) -> tuple[list, str]:
        """Discover the models the key can use again. Keeps the list when
        none are found; returns the models found and, if none, why."""
        found = discover(provider.provider_type, provider.base_url, provider.api_key)
        if found.models:
            provider.available_models = found.models
            provider.save(update_fields=["available_models"])
        return found.models, ("" if found.models else found.reason or "")

    @staticmethod
    def set_role(tenant, role: str, *, provider_id=None, model: str = "") -> LLMRole | None:
        """Point a role at a provider and model; no provider clears it
        (returns None)."""
        if role not in LLMRole.Name.values:
            raise LLMProviderError(f"Unknown role {role!r}; one of: {', '.join(LLMRole.Name.values)}.")
        if not provider_id:
            LLMRole.objects.filter(tenant=tenant, name=role).delete()
            return None
        provider = LLMProvider.objects.filter(tenant=tenant, pk=provider_id).first()
        if provider is None:
            raise NotFoundError("Provider not found.")
        model = (model or "").strip()
        if not model:
            raise LLMProviderError("Select a model for the role.")
        row, _ = LLMRole.objects.update_or_create(
            tenant=tenant, name=role, defaults={"provider": provider, "model": model}
        )
        return row

    @staticmethod
    def auto_name(tenant, provider_type: str) -> str:
        """The type's label, numbered when the workspace already has one."""
        label = dict(LLMProviderType.choices).get(provider_type, provider_type)
        existing = set(LLMProvider.objects.filter(tenant=tenant).values_list("display_name", flat=True))
        if label not in existing:
            return label
        n = 2
        while f"{label} {n}" in existing:
            n += 1
        return f"{label} {n}"
