from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.ai_usage import TokenCount


@dataclass(frozen=True)
class ProviderUsage:
    """One provider's models, most used first."""

    provider_id: object
    name: str
    models: tuple = field(default_factory=tuple)  # (ModelUsage, ...)

    @property
    def tokens(self) -> TokenCount:
        return TokenCount.total_of(m.tokens for m in self.models)
