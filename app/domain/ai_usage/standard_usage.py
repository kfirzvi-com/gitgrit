from __future__ import annotations

from dataclasses import dataclass

from app.domain.ai_usage.token_count import TokenCount


@dataclass(frozen=True)
class StandardUsage:
    """One LLM standard's tokens over a period, and how many runs spent them."""

    standard_id: object
    name: str
    tokens: TokenCount
    runs: int

    @property
    def per_run(self) -> int:
        return self.tokens.total // self.runs if self.runs else 0
