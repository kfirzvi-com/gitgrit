"""AI usage: how many tokens a workspace spends on which models, for what,
and the budgets that cap it.

Pure Python (no Django): the vocabulary and rules every layer shares.

* ``TokenCount`` — input and output tokens (priced apart) and calls;
* ``UsageCategory`` — what the tokens were spent on (the map, LLM standards);
* ``BudgetPeriod`` — the window a budget counts over (day, week, month);
* ``BudgetLevel`` / ``TokenBudget`` — how far a budget is used, when to warn
  and when a budget stops further runs;
* ``BudgetSummary`` — how many budgets are fine, nearly used, used up;
* ``ModelAccess`` — whether a model may run: only with a budget, and not
  once a stop-at-limit budget is used up;
* ``StandardUsageDistribution`` — which LLM standards spend far more than others.
"""
from app.domain.ai_usage.budget_level import BudgetLevel
from app.domain.ai_usage.budget_period import BudgetPeriod
from app.domain.ai_usage.budget_summary import BudgetSummary
from app.domain.ai_usage.model_access import Denial, ModelAccess
from app.domain.ai_usage.standard_usage import StandardUsage
from app.domain.ai_usage.standard_usage_distribution import StandardUsageDistribution
from app.domain.ai_usage.token_budget import TokenBudget
from app.domain.ai_usage.token_count import TokenCount
from app.domain.ai_usage.usage_category import UsageCategory

__all__ = [
    "BudgetLevel",
    "BudgetPeriod",
    "BudgetSummary",
    "Denial",
    "ModelAccess",
    "StandardUsage",
    "StandardUsageDistribution",
    "TokenBudget",
    "TokenCount",
    "UsageCategory",
]
