from __future__ import annotations

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from app.domain.ai_usage import BudgetPeriod, Denial, ModelAccess, TokenCount
from app.domain.models import LLMBudget, LLMProvider, LLMUsage, Notification


class BudgetWatch:
    """Reads a model's usage against its budgets: how much each budget's
    period has used, whether the model may run now, and announcing a
    budget's warning levels once per period."""

    @staticmethod
    def used(budget: LLMBudget, now=None) -> TokenCount:
        """Tokens the budget's model spent in its current period."""
        now = timezone.localtime(now)
        period = BudgetPeriod(budget.period)
        sums = LLMUsage.objects.filter(
            tenant_id=budget.tenant_id,
            provider_id=budget.provider_id,
            model=budget.model,
            created_at__gte=period.starts(now),
        ).aggregate(i=Sum("input_tokens"), o=Sum("output_tokens"), c=Sum("calls"))
        return TokenCount(sums["i"] or 0, sums["o"] or 0, sums["c"] or 0)

    @classmethod
    def refusal(cls, tenant, provider_id, model, now=None) -> str | None:
        """Why this model may not run now (``ai_usage.ModelAccess``), in
        words for the run's message; None when it may."""
        budgets = list(
            LLMBudget.objects.filter(tenant=tenant, provider_id=provider_id, model=model).select_related("provider")
        )
        access = ModelAccess.of((b.rules, cls.used(b, now)) for b in budgets)
        if access.allowed:
            return None
        if access.denial is Denial.USED_UP:
            return cls.stop_message(budgets[access.budget], now)
        provider = LLMProvider.objects.filter(tenant=tenant, pk=provider_id).first()
        name = f"{provider.display_name} {model}" if provider else model
        return (
            f"No AI budget for {name}. Only models with a budget can run; a workspace owner or admin "
            "sets one in workspace settings, under LLM Providers."
        )

    @classmethod
    def check(cls, tenant, provider_id, model, now=None) -> None:
        """After usage was recorded: announce each budget of the model that
        crossed a level it has not announced yet this period."""
        from app.application.notifications.service import raise_notification

        now = timezone.localtime(now)
        for budget in LLMBudget.objects.filter(tenant=tenant, provider_id=provider_id, model=model).select_related("provider"):
            key = BudgetPeriod(budget.period).key(now)
            used = cls.used(budget, now)
            level = budget.rules.to_announce(used, budget.announced(key))
            if level is None:
                continue
            with transaction.atomic():
                budget.announced_period, budget.announced_level = key, str(level)
                budget.save(update_fields=["announced_period", "announced_level", "updated_at"])
                raise_notification(Notification.ai_budget(budget=budget, level=level, used=used))

    @staticmethod
    def stop_message(budget: LLMBudget, now=None) -> str:
        """Why a run was skipped, and when it can run again."""
        now = timezone.localtime(now)
        resets = BudgetPeriod(budget.period).ends(now)
        return (
            f"AI budget used up: {budget.provider.display_name} {budget.model} "
            f"({BudgetPeriod(budget.period).label.lower()} budget). Runs on this model resume "
            f"{resets:%b} {resets.day}, {resets:%H:%M}, or raise the budget in workspace settings."
        )
