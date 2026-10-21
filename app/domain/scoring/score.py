from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Score:
    """A complete commit's score. ``value`` is None when no result could be
    averaged (every one errored); ``reason`` says why a failed commit is 0."""

    value: int | None
    failed: bool = False
    reason: str = ""
