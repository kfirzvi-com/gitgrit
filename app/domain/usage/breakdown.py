from __future__ import annotations

from collections.abc import Iterable

from app.domain.usage.execution_slice import ExecutionSlice
from app.domain.usage.share import Share


class Breakdown:
    """Usage split two ways — by project and by trigger — as ``Share``s,
    most executions first, from any set of ``ExecutionSlice``s (a day's, a
    month's)."""

    def __init__(self, slices: Iterable[ExecutionSlice]):
        self.slices = tuple(slices)

    def by_project(self) -> list[Share]:
        names = {s.project_id: s.project_name for s in self.slices}
        return self._ranked(names, lambda s: s.project_id)

    def by_trigger(self) -> list[Share]:
        return self._ranked({s.trigger: s.trigger for s in self.slices}, lambda s: s.trigger)

    def _ranked(self, names: dict, key) -> list[Share]:
        totals: dict = {}
        for s in self.slices:
            runs, ms = totals.get(key(s), (0, 0))
            totals[key(s)] = (runs + s.executions, ms + s.run_ms)
        shares = [Share(names[k], runs, ms) for k, (runs, ms) in totals.items() if runs or ms]
        return sorted(shares, key=lambda s: (-s.executions, -s.run_ms, s.name))
