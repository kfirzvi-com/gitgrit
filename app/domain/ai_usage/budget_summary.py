from __future__ import annotations

from dataclasses import dataclass

from app.domain.ai_usage.budget_level import BudgetLevel


@dataclass(frozen=True)
class BudgetSummary:
    """Where a workspace's AI budgets stand: how many are fine, nearly used
    (80%+) and used up, and how many of those stop runs. What a manager
    reads instead of a token total, which would add up tokens of models
    priced far apart."""

    ok: int = 0
    near: int = 0
    used_up: int = 0
    stopping: int = 0

    @property
    def total(self) -> int:
        return self.ok + self.near + self.used_up

    @property
    def worst(self) -> BudgetLevel:
        if self.used_up:
            return BudgetLevel.REACHED
        if self.near:
            return BudgetLevel.NEAR
        return BudgetLevel.OK

    @classmethod
    def of(cls, budgets) -> "BudgetSummary":
        """``budgets``: (TokenBudget, TokenCount used) pairs."""
        counts = {level: 0 for level in BudgetLevel}
        stopping = 0
        for rules, used in budgets:
            counts[rules.level(used)] += 1
            stopping += rules.stops_runs(used)
        return cls(counts[BudgetLevel.OK], counts[BudgetLevel.NEAR], counts[BudgetLevel.REACHED], stopping)
