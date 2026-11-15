from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenCount:
    """Tokens spent: input (what was sent) and output (what the model wrote)
    are counted apart because providers price them apart; ``calls`` is how
    many requests they took."""

    input: int = 0
    output: int = 0
    calls: int = 0

    def __post_init__(self):
        if min(self.input, self.output, self.calls) < 0:
            raise ValueError("Token counts are never negative")

    def __add__(self, other: "TokenCount") -> "TokenCount":
        return TokenCount(self.input + other.input, self.output + other.output, self.calls + other.calls)

    @property
    def total(self) -> int:
        return self.input + self.output

    @classmethod
    def total_of(cls, counts) -> "TokenCount":
        result = cls()
        for count in counts:
            result = result + count
        return result
