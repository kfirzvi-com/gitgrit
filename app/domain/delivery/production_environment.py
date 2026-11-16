from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_NAMES = ("production", "prod")

_NEGATIONS = {"non", "not"}

_SEPARATORS = re.compile(r"[\s\-_./:]+")


@dataclass(frozen=True)
class ProductionEnvironment:
    """Which deployment environments count as production. An environment
    counts when one of the words in its name is one of ``names``, so
    ``production``, ``prod-eu`` and ``us/production`` match while
    ``preprod``, ``non-prod`` and ``staging`` do not."""

    names: tuple[str, ...] = DEFAULT_NAMES

    def __post_init__(self):
        cleaned = tuple(dict.fromkeys(name.strip().lower() for name in self.names if name.strip()))
        object.__setattr__(self, "names", cleaned or DEFAULT_NAMES)

    @classmethod
    def from_text(cls, text: str) -> ProductionEnvironment:
        """Names typed as a comma-separated list; blank means the default."""
        return cls(tuple(text.split(",")))

    def matches(self, environment: str) -> bool:
        words = [word for word in _SEPARATORS.split(environment.lower()) if word]
        return any(
            word in self.names and (index == 0 or words[index - 1] not in _NEGATIONS)
            for index, word in enumerate(words)
        )

    def as_text(self) -> str:
        return ", ".join(self.names)
