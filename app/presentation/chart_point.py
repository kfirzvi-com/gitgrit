from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartPoint:
    """One point a chart draws: where, its value and its label."""

    x: float
    y: float
    value: int
    label: str
