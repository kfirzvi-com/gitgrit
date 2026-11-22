from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UsageMetric:
    """One meter's card in the Usage section — executions or run time —
    and the chart's switch to it: its total and the figures that explain it,
    each labeled with what it counts. ``key`` also names its colour
    (``u-bg-<key>`` in the section), so the card, its bars and its details
    read as one."""

    key: str
    label: str
    total: str
    unit: str
    figures: tuple[tuple[str, str], ...]
    note: str = ""
