from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InfoTip:
    """A short explanation behind an ⓘ: what a number is, how it is counted
    across the workspace, and what good looks like. ``dora`` marks one of
    DORA's metrics, which shows DORA's bands as a legend. Each part is one
    sentence or two, so the tip reads at a glance."""

    title: str
    how: str
    good: str = ""
    dora: bool = False
