from __future__ import annotations

from dataclasses import dataclass

from app.domain.ai_usage.budget_level import BudgetLevel
from app.domain.ai_usage.budget_period import BudgetPeriod
from app.domain.ai_usage.token_count import TokenCount


@dataclass(frozen=True)
class TokenBudget:
    """A cap on one model's tokens over a period. Input and output are capped
    apart (they are priced apart); either limit may be left unset. A budget
    is as far used as its most used limit. Read like a fuel tank: it starts
    full, and ``low_at_percent`` is the low-fuel mark, how much is left when
    it warns (unset: it only says when used up); there is no default, each
    budget's owner picks it. With ``stop_at_limit`` a
    reached budget stops new runs on the model until the period turns over;
    otherwise it only warns."""

    period: BudgetPeriod
    input_limit: int | None = None
    output_limit: int | None = None
    stop_at_limit: bool = False
    low_at_percent: int | None = None

    def __post_init__(self):
        if self.input_limit is None and self.output_limit is None:
            raise ValueError("A budget needs an input or an output limit")
        for limit in (self.input_limit, self.output_limit):
            if limit is not None and limit <= 0:
                raise ValueError("A limit is a positive number of tokens")
        if self.low_at_percent is not None and not 1 <= self.low_at_percent <= 99:
            raise ValueError("Set the low mark between 1% and 99% left")

    @property
    def warn_at(self) -> float | None:
        """The share used at which the budget is low (its mark, as used)."""
        return 1 - self.low_at_percent / 100 if self.low_at_percent is not None else None

    def level_of(self, share: float | None) -> BudgetLevel:
        """The level one limit's share alone stands at (unset limit: OK)."""
        return BudgetLevel.OK if share is None else BudgetLevel.of_share(share, self.warn_at)

    def input_share(self, used: TokenCount) -> float | None:
        return used.input / self.input_limit if self.input_limit else None

    def output_share(self, used: TokenCount) -> float | None:
        return used.output / self.output_limit if self.output_limit else None

    def share(self, used: TokenCount) -> float:
        """The most used limit's share (1.0 = used up)."""
        return max(s for s in (self.input_share(used), self.output_share(used)) if s is not None)

    def level(self, used: TokenCount) -> BudgetLevel:
        return BudgetLevel.of_share(self.share(used), self.warn_at)

    def stops_runs(self, used: TokenCount) -> bool:
        return self.stop_at_limit and self.level(used) is BudgetLevel.REACHED

    def to_announce(self, used: TokenCount, announced: BudgetLevel) -> BudgetLevel | None:
        """The level to tell the admins about now, given the highest one
        already announced this period: each of NEAR (when the budget has a
        warning threshold) and REACHED is announced once per period, never a
        step back down."""
        level = self.level(used)
        return level if level.rank > announced.rank else None
