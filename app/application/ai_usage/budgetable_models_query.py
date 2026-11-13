from __future__ import annotations

from app.domain.ai_usage import BudgetableModel, BudgetableModels
from app.domain.models import LLMBudget, LLMProvider, LLMRole


class BudgetableModelsQuery:
    """Reads a workspace's roles, budgets and providers for
    ``BudgetableModels``, which decides the list. Shared by workspace
    settings and the API."""

    @staticmethod
    def for_workspace(tenant) -> tuple[BudgetableModel, ...]:
        return BudgetableModels.of(
            roles=[
                (str(r.provider_id), r.provider.display_name, r.model, r.get_name_display())
                for r in LLMRole.objects.filter(tenant=tenant).select_related("provider").order_by("name")
            ],
            budgeted=[
                (str(b.provider_id), b.provider.display_name, b.model)
                for b in LLMBudget.objects.filter(tenant=tenant).select_related("provider").order_by("model")
            ],
            offered=[
                (str(p.pk), p.display_name, model)
                for p in LLMProvider.objects.filter(tenant=tenant).order_by("display_name")
                for model in p.available_models or []
            ],
        )
