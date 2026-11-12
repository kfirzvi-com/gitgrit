from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.ai_usage import TokenCount


@dataclass(frozen=True)
class ModelUsage:
    """One model's tokens in the report's window, with its budgets, each
    paired with what that budget's own period has used."""

    model: str
    tokens: TokenCount
    budgets: tuple = field(default_factory=tuple)  # ((LLMBudget, TokenCount used), ...)
