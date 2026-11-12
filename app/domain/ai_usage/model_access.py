from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Denial(StrEnum):
    """Why a model may not run now."""

    NO_BUDGET = "no_budget"  # nobody has given it a budget yet
    USED_UP = "used_up"  # a budget that stops runs is used up


@dataclass(frozen=True)
class ModelAccess:
    """Whether GitGrit may call a model now. Budgets are an allow-list: a
    model with no budget does not run at all, so nothing spends before an
    owner or admin has decided it may; a model whose stop-at-limit budget is
    used up waits for the period to turn over. ``budget`` is the position,
    in what was checked, of the budget that stopped it."""

    denial: Denial | None = None
    budget: int | None = None

    @property
    def allowed(self) -> bool:
        return self.denial is None

    @classmethod
    def of(cls, budgets) -> "ModelAccess":
        """``budgets``: the model's (TokenBudget, TokenCount used) pairs."""
        budgets = list(budgets)
        if not budgets:
            return cls(Denial.NO_BUDGET)
        for position, (rules, used) in enumerate(budgets):
            if rules.stops_runs(used):
                return cls(Denial.USED_UP, position)
        return cls()
