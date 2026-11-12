from __future__ import annotations

from app.domain.ai_usage import BudgetSummary
from app.presentation.budget_row import BudgetRow

# How many standards the distribution lists before "and N more".
STANDARDS_SHOWN = 8


class AIUsageSection:
    """What the dashboard's AI section draws from an ``AIUsageReport``: bar
    lengths relative to the biggest row of each list, and each model's
    budgets as meters."""

    def __init__(self, report):
        self.report = report
        models = [m for p in report.providers for m in p.models]
        self.max_model = max([m.tokens.input for m in models] + [m.tokens.output for m in models] + [1])
        self.max_category = max([t.total for _, t in report.categories] + [1])

    @property
    def budgets(self) -> BudgetSummary:
        return BudgetSummary.of(
            (budget.rules, used) for p in self.report.providers for m in p.models for budget, used in m.budgets
        )

    @property
    def providers(self):
        """(provider, [(model, [BudgetRow])])."""
        return [
            (provider, [(model, [BudgetRow(b, used) for b, used in model.budgets]) for model in provider.models])
            for provider in self.report.providers
        ]

    @property
    def standards(self):
        dist = self.report.standards
        return [
            {"usage": p, "share": dist.share(p), "heavy": dist.is_heavy(p), "times": dist.times_median(p)}
            for p in dist.standards[:STANDARDS_SHOWN]
        ]

    @property
    def more_standards(self) -> int:
        return max(len(self.report.standards.standards) - STANDARDS_SHOWN, 0)
