from __future__ import annotations

from enum import StrEnum


class BudgetLevel(StrEnum):
    """How far a budget is used, mildest first."""

    OK = "ok"
    NEAR = "near"  # low: at or under the budget's own low mark
    REACHED = "reached"  # a limit is used up

    @property
    def rank(self) -> int:
        return {BudgetLevel.OK: 0, BudgetLevel.NEAR: 1, BudgetLevel.REACHED: 2}[self]

    @classmethod
    def of_share(cls, share: float, warn_at: float | None = None) -> "BudgetLevel":
        """``share``: how much of a limit is used (1.0 = all of it);
        ``warn_at``: the share at which the budget warns, or None for a
        budget that only says when it is used up."""
        if share >= 1:
            return cls.REACHED
        if warn_at is not None and share >= warn_at:
            return cls.NEAR
        return cls.OK
