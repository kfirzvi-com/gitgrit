from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from app.domain.ai_usage import BudgetPeriod, TokenCount


@dataclass(frozen=True)
class BudgetRow:
    """A budget as a settings row or a dashboard bar: its limits, what its
    current period has used, and how far."""

    budget: object  # LLMBudget
    used: TokenCount
    now: datetime = field(default_factory=timezone.localtime)

    # The window the budget counts now (local time), and when it starts over.

    @property
    def starts(self):
        return self.period.starts(self.now)

    @property
    def resets(self):
        return self.period.ends(self.now)

    @property
    def resets_short(self) -> str:
        """When it starts over, in a word or two: ``midnight``, ``Mon``,
        ``Dec 1``."""
        if self.period is BudgetPeriod.DAY:
            return "midnight"
        resets = self.resets
        if (resets.date() - self.now.date()).days < 7:
            return f"{resets:%a}"
        return f"{resets:%b} {resets.day}"

    @property
    def window(self) -> str:
        """``Nov 12`` for a day, ``Nov 9 – Nov 15`` for a week or month."""
        first, last = self.starts.date(), self.period.last_day(self.now)
        if first == last:
            return f"{first:%b} {first.day}"
        return f"{first:%b} {first.day} – {last:%b} {last.day}"

    @property
    def rules(self):
        return self.budget.rules

    @property
    def period(self) -> BudgetPeriod:
        return BudgetPeriod(self.budget.period)

    @property
    def input_share(self):
        return self.rules.input_share(self.used)

    @property
    def output_share(self):
        return self.rules.output_share(self.used)

    @property
    def input_level(self) -> str:
        return str(self.rules.level_of(self.input_share))

    @property
    def output_level(self) -> str:
        return str(self.rules.level_of(self.output_share))

    @property
    def level(self) -> str:
        return str(self.rules.level(self.used))

    @property
    def stops_runs(self) -> bool:
        return self.rules.stops_runs(self.used)
