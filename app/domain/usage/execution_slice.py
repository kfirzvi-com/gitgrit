from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionSlice:
    """Some of a day's executions: those one project ran on one trigger
    (a push, a pull request, a manual run, an upload). The project's name is
    kept as it was, so usage stays readable after the project is deleted."""

    project_id: str
    project_name: str
    trigger: str
    executions: int
