from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Count, Sum
from django.utils import timezone

from app.application.ai_usage.budget_watch import BudgetWatch
from app.application.ai_usage.model_usage import ModelUsage
from app.application.ai_usage.provider_usage import ProviderUsage
from app.domain.ai_usage import BudgetPeriod, StandardUsage, StandardUsageDistribution, TokenCount, UsageCategory
from app.domain.models import LLMBudget, LLMRole, LLMUsage


@dataclass(frozen=True)
class AIUsageReport:
    """A workspace's AI spend over the current day, week or month:

    - ``providers``: each provider's models with input/output tokens and
      their budgets; models with a budget or a configured role are listed
      even before they spend anything;
    - ``categories``: tokens per kind of work (the map, LLM standards);
    - ``standards``: how LLM-standard tokens split between standards."""

    period: BudgetPeriod
    total: TokenCount
    providers: tuple = field(default_factory=tuple)
    categories: tuple = field(default_factory=tuple)  # ((UsageCategory, TokenCount), ...)
    standards: StandardUsageDistribution = None

    @property
    def is_empty(self) -> bool:
        return not self.providers

    @classmethod
    def for_workspace(cls, tenant, period: BudgetPeriod, now=None) -> "AIUsageReport":
        now = timezone.localtime(now)
        usage = LLMUsage.objects.filter(tenant=tenant, created_at__gte=period.starts(now))

        by_model = defaultdict(TokenCount)
        names = {}
        for row in usage.values("provider_id", "provider_name", "model").annotate(
            i=Sum("input_tokens"), o=Sum("output_tokens"), c=Sum("calls")
        ):
            key = (row["provider_id"], row["model"])
            by_model[key] = TokenCount(row["i"] or 0, row["o"] or 0, row["c"] or 0)
            names[row["provider_id"]] = row["provider_name"]

        budgets = defaultdict(list)
        for budget in LLMBudget.objects.filter(tenant=tenant).select_related("provider").order_by("period"):
            budgets[(budget.provider_id, budget.model)].append((budget, BudgetWatch.used(budget, now)))
            names[budget.provider_id] = budget.provider.display_name
        for role in LLMRole.objects.filter(tenant=tenant).select_related("provider"):
            by_model.setdefault((role.provider_id, role.model), TokenCount())
            names[role.provider_id] = role.provider.display_name
        for key in budgets:
            by_model.setdefault(key, TokenCount())

        models_of = defaultdict(list)
        for (provider_id, model), tokens in by_model.items():
            models_of[provider_id].append(ModelUsage(model, tokens, tuple(budgets.get((provider_id, model), ()))))
        providers = tuple(
            sorted(
                (
                    ProviderUsage(pid, names.get(pid) or "Unknown provider",
                                  tuple(sorted(ms, key=lambda m: (-m.tokens.total, m.model))))
                    for pid, ms in models_of.items()
                ),
                key=lambda p: (-p.tokens.total, p.name.lower()),
            )
        )

        categories = {c: TokenCount() for c in UsageCategory}
        for row in usage.values("category").annotate(i=Sum("input_tokens"), o=Sum("output_tokens"), c=Sum("calls")):
            categories[UsageCategory(row["category"])] = TokenCount(row["i"] or 0, row["o"] or 0, row["c"] or 0)

        standards = [
            StandardUsage(
                standard_id=row["standard_id"],
                name=row["standard_name"] or "Deleted standard",
                tokens=TokenCount(row["i"] or 0, row["o"] or 0, row["c"] or 0),
                runs=row["runs"],
            )
            for row in usage.filter(category=UsageCategory.STANDARD)
            .values("standard_id", "standard_name")
            .annotate(i=Sum("input_tokens"), o=Sum("output_tokens"), c=Sum("calls"), runs=Count("execution_id", distinct=True))
        ]

        return cls(
            period=period,
            total=TokenCount.total_of(categories.values()),
            providers=providers,
            categories=tuple(categories.items()),
            standards=StandardUsageDistribution(standards),
        )
