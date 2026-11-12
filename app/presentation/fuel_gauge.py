from __future__ import annotations

from dataclasses import dataclass

from app.domain.ai_usage import BudgetLevel, BudgetSummary
from app.presentation.budget_row import BudgetRow

# How many tanks the cluster has room for; the rest are counted.
TANKS_SHOWN = 6


@dataclass(frozen=True)
class FuelTank:
    """One budgeted model's tank: how much of its budget is left (its most
    used limit decides), and its level."""

    row: BudgetRow
    percent_left: int
    level: BudgetLevel

    @property
    def low_at_percent(self) -> int | None:
        """Where the low-fuel mark sits on the tank (None: no early warning)."""
        return self.row.budget.low_at_percent


class FuelGauge:
    """The cockpit's AI fuel gauge: a vertical tank per budgeted provider and
    model, filled to what is left of its budget (F full, E used up), the
    emptiest first. Models are priced apart, so each tank stands alone; no
    tank adds up another's tokens."""

    def __init__(self, budget_rows, blocked: int = 0):
        """``blocked``: how many of the workspace's models have no budget,
        so they cannot run (budgets are an allow-list)."""
        self.blocked = blocked
        rows = sorted(
            (r for r in budget_rows if isinstance(r, BudgetRow)), key=lambda r: -r.rules.share(r.used)
        )
        self.tanks = [
            FuelTank(r, max(0, round((1 - r.rules.share(r.used)) * 100)), r.rules.level(r.used))
            for r in rows[:TANKS_SHOWN]
        ]
        self.more = max(len(rows) - TANKS_SHOWN, 0)
        self.summary = BudgetSummary.of((r.rules, r.used) for r in rows)

    @property
    def has_budget(self) -> bool:
        return bool(self.tanks)
