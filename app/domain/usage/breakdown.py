from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from app.domain.usage.execution_slice import ExecutionSlice


class Breakdown:
    """Executions split two ways — by project and by trigger — biggest
    first, from any set of ``ExecutionSlice``s (a day's, a month's)."""

    def __init__(self, slices: Iterable[ExecutionSlice]):
        self.slices = tuple(slices)

    def by_project(self) -> list[tuple[str, int]]:
        names: dict[str, str] = {}
        counts: Counter = Counter()
        for s in self.slices:
            names[s.project_id] = s.project_name
            counts[s.project_id] += s.executions
        return [(names[pid], n) for pid, n in self._ranked(counts)]

    def by_trigger(self) -> list[tuple[str, int]]:
        counts: Counter = Counter()
        for s in self.slices:
            counts[s.trigger] += s.executions
        return self._ranked(counts)

    @staticmethod
    def _ranked(counts: Counter) -> list[tuple[str, int]]:
        return sorted(((k, n) for k, n in counts.items() if n), key=lambda kv: (-kv[1], kv[0]))
