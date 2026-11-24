from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass(frozen=True)
class DeliveryColumn:
    """One week of a delivery chart: its bar and, when the chart has one, its
    point on the line (x, y in a 0–100 box)."""

    starts: date
    value: int
    height: int
    line_value: int = 0
    x: float = 0.0
    y: float = 100.0


class DeliveryChart:
    """Weekly bars, optionally with a line over them, each scaled to its own
    busiest week (bars fill the height, the line keeps a margin on top)."""

    def __init__(self, starts: Sequence[date], bars: Sequence[int], line: Sequence[int] | None = None):
        self.has_line = line is not None
        line = line if line is not None else [0] * len(bars)
        most, most_line = max(bars, default=0), max(line, default=0)
        width = 100 / len(bars) if bars else 0
        self.columns = [
            DeliveryColumn(
                starts=start,
                value=value,
                height=round(100 * value / most) if most else 0,
                line_value=line_value,
                x=round(width * (index + 0.5), 2),
                y=round(100 - 92 * line_value / most_line, 2) if most_line else 100.0,
            )
            for index, (start, value, line_value) in enumerate(zip(starts, bars, line))
        ]

    @property
    def points(self) -> str:
        return " ".join(f"{column.x},{column.y}" for column in self.columns)
