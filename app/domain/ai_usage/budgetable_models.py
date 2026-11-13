from __future__ import annotations

from app.domain.ai_usage.budgetable_model import BudgetableModel


class BudgetableModels:
    """Which models a workspace can set a budget on, in the order an admin
    wants them: the models its roles use first (GitGrit calls those, so
    they are blocked until budgeted), then every model that already has a
    budget (so editing one always finds it, even after its provider stopped
    listing it), then each provider's other known models. Each provider and
    model appears once, with every role that uses it."""

    @staticmethod
    def of(*, roles=(), budgeted=(), offered=()) -> tuple[BudgetableModel, ...]:
        """``roles``: (provider id, provider name, model, role label), in
        role order; ``budgeted`` and ``offered``: (provider id, provider
        name, model), the models with a budget and the ones the providers'
        keys can use."""
        rows: dict[tuple, dict] = {}

        def add(provider_id, provider_name, model, role=None):
            row = rows.setdefault((provider_id, model), {"name": provider_name, "roles": []})
            if role and role not in row["roles"]:
                row["roles"].append(role)

        for provider_id, provider_name, model, role in roles:
            add(provider_id, provider_name, model, role)
        budgeted = list(budgeted)
        for provider_id, provider_name, model in budgeted:
            add(provider_id, provider_name, model)
        for provider_id, provider_name, model in offered:
            add(provider_id, provider_name, model)
        with_budget = {(provider_id, model) for provider_id, _, model in budgeted}
        return tuple(
            BudgetableModel(
                provider_id=provider_id,
                provider_name=row["name"],
                model=model,
                roles=tuple(row["roles"]),
                has_budget=(provider_id, model) in with_budget,
            )
            for (provider_id, model), row in rows.items()
        )
