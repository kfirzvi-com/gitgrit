from __future__ import annotations

from statistics import median

from app.domain.ai_usage.standard_usage import StandardUsage

# A standard is heavy when it spends at least this many times the median.
HEAVY_FACTOR = 2
# Fewer standards than this have no meaningful median to stand out from.
MIN_STANDARDS = 3


class StandardUsageDistribution:
    """How a period's LLM-standard tokens split between standards: biggest
    first, each with its share of the total, and which ones spend far more
    than the others (at least twice the median standard)."""

    def __init__(self, standards):
        self.standards: list[StandardUsage] = sorted(standards, key=lambda p: (-p.tokens.total, p.name.lower()))
        self.total = sum(p.tokens.total for p in self.standards)
        totals = [p.tokens.total for p in self.standards]
        self._median = median(totals) if totals else 0

    def share(self, standard: StandardUsage) -> float:
        return standard.tokens.total / self.total if self.total else 0.0

    def is_heavy(self, standard: StandardUsage) -> bool:
        if len(self.standards) < MIN_STANDARDS or not self._median:
            return False
        return standard.tokens.total >= HEAVY_FACTOR * self._median

    @property
    def heavy(self) -> list[StandardUsage]:
        return [p for p in self.standards if self.is_heavy(p)]

    def times_median(self, standard: StandardUsage) -> float:
        return round(standard.tokens.total / self._median, 1) if self._median else 0.0
