from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommitScoreValue:
    """A commit's computed score: ``value`` 0-100 (None when no run could be
    averaged, every one errored), whether a Required standard failed it (the
    value is then 0) and why."""

    value: int | None
    failed_by_required_standard: bool = False
    failure_reason: str = ""
