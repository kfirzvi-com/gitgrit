from __future__ import annotations

from app.domain.ai_usage import BudgetPeriod, TokenBudget
from app.domain.models import LLMBudget, LLMProvider


class BudgetError(ValueError):
    """A budget that cannot be saved, with why, in words for the admin."""


class BudgetService:
    """Setting and removing a workspace's AI budgets. One budget per
    provider, model and period. Who may do this is the caller's check
    (workspace owners and admins)."""

    @staticmethod
    def save(tenant, *, provider_id, model: str, period: str, input_limit, output_limit,
             stop_at_limit: bool, low_at_percent=None, budget_id=None) -> LLMBudget:
        """Create a budget, or change the one ``budget_id`` names (its model
        and period may change too)."""
        provider = LLMProvider.objects.filter(tenant=tenant, pk=provider_id).first() if provider_id else None
        if provider is None:
            raise BudgetError("Pick a provider and model.")
        model = (model or "").strip()
        if not model:
            raise BudgetError("Pick a model.")
        try:
            period = BudgetPeriod(period)
        except ValueError:
            raise BudgetError("Pick a period: day, week or month.") from None
        try:
            # The domain's rules decide what a valid budget is.
            rules = TokenBudget(period, _limit(input_limit), _limit(output_limit), bool(stop_at_limit),
                                _percent(low_at_percent))
        except ValueError as exc:
            raise BudgetError(f"{exc}.") from None
        existing = LLMBudget.objects.filter(tenant=tenant, pk=budget_id).first() if budget_id else None
        clash = LLMBudget.objects.filter(tenant=tenant, provider=provider, model=model, period=str(period))
        if existing:
            clash = clash.exclude(pk=existing.pk)
        if clash.exists():
            raise BudgetError(f"{model} already has a {period.label.lower()} budget; edit that one.")
        budget = existing or LLMBudget(tenant=tenant)
        budget.provider, budget.model, budget.period = provider, model, str(period)
        budget.input_limit, budget.output_limit = rules.input_limit, rules.output_limit
        budget.stop_at_limit, budget.low_at_percent = rules.stop_at_limit, rules.low_at_percent
        # A changed budget is judged afresh: warn again if still over.
        budget.announced_period, budget.announced_level = "", ""
        budget.save()
        return budget

    @staticmethod
    def delete(tenant, budget_id) -> None:
        LLMBudget.objects.filter(tenant=tenant, pk=budget_id).delete()


def _percent(value):
    """A low mark as typed: blank is none; a trailing % is fine."""
    text = str(value or "").replace("%", "").strip()
    if not text:
        return None
    if not text.isdigit():
        raise BudgetError("Set the low mark as a whole percentage, like 20.")
    return int(text)


def _limit(value):
    """A limit as typed: blank is no limit; commas and spaces are allowed."""
    text = str(value or "").replace(",", "").replace("_", "").replace(" ", "").strip()
    if not text:
        return None
    if not text.isdigit():
        raise BudgetError("Limits are whole numbers of tokens.")
    return int(text)
