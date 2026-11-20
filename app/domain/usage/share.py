from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Share:
    """One project's or one trigger's part of some usage: its executions and
    the sandbox time they took."""

    name: str
    executions: int
    run_ms: int = 0

    @property
    def minutes(self) -> float:
        return self.run_ms / 60_000
