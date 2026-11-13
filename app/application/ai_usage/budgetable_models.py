from __future__ import annotations

from app.application.ai_usage.budgetable_model import BudgetableModel
from app.domain.models import LLMBudget, LLMProvider, LLMRole


class BudgetableModels:
    """The models a workspace can set a budget on, role models first (the
    ones GitGrit calls), then every model that already has a budget (so
    editing one always finds it), then each provider's other known models.
    Shared by workspace settings and the API."""

    @staticmethod
    def for_workspace(tenant) -> list[BudgetableModel]:
        budgeted = set(LLMBudget.objects.filter(tenant=tenant).values_list("provider_id", "model"))
        rows: dict[tuple, dict] = {}

        def add(provider, model, role=None):
            key = (provider.pk, model)
            row = rows.setdefault(key, {"provider": provider, "model": model, "roles": []})
            if role and role not in row["roles"]:
                row["roles"].append(role)

        for role in LLMRole.objects.filter(tenant=tenant).select_related("provider").order_by("name"):
            add(role.provider, role.model, role.get_name_display())
        for budget in LLMBudget.objects.filter(tenant=tenant).select_related("provider").order_by("model"):
            add(budget.provider, budget.model)
        for provider in LLMProvider.objects.filter(tenant=tenant).order_by("display_name"):
            for model in provider.available_models or []:
                add(provider, model)
        return [
            BudgetableModel(
                provider_id=str(row["provider"].pk),
                provider_name=row["provider"].display_name,
                model=row["model"],
                roles=tuple(row["roles"]),
                has_budget=key in budgeted,
            )
            for key, row in rows.items()
        ]
