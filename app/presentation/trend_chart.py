from __future__ import annotations

from app.presentation.chart_point import ChartPoint

# The chart's drawing area, in viewBox units (560 x 240).
LEFT, RIGHT, TOP, BOTTOM = 40, 540, 20, 200
TICKS = 4


class TrendChart:
    """Where the healthy-projects trend draws: one point per TrendPoint,
    healthy as a line over the total as a dashed line, on a 0-to-max
    scale."""

    def __init__(self, points):
        self.points = tuple(points)
        self.top_value = max([p.total for p in self.points] + [1])

    def _x(self, i):
        if len(self.points) == 1:
            return (LEFT + RIGHT) / 2
        return round(LEFT + (RIGHT - LEFT) * i / (len(self.points) - 1), 2)

    def _y(self, value):
        return round(BOTTOM - (BOTTOM - TOP) * value / self.top_value, 2)

    @property
    def healthy(self) -> list[ChartPoint]:
        return [
            ChartPoint(self._x(i), self._y(p.healthy), p.healthy, f"{p.day:%b} {p.day.day}")
            for i, p in enumerate(self.points)
        ]

    @property
    def healthy_line(self) -> str:
        return " ".join(f"{p.x},{p.y}" for p in self.healthy)

    @property
    def total_line(self) -> str:
        return " ".join(f"{self._x(i)},{self._y(p.total)}" for i, p in enumerate(self.points))

    @property
    def area(self) -> str:
        pts = self.healthy
        if not pts:
            return ""
        line = " L ".join(f"{p.x} {p.y}" for p in pts)
        return f"M {line} L {pts[-1].x} {BOTTOM} L {pts[0].x} {BOTTOM} Z"

    @property
    def ticks(self) -> list[tuple[float, int]]:
        """(y, value) for each grid line, top first."""
        return [
            (round(TOP + (BOTTOM - TOP) * i / TICKS, 2), round(self.top_value * (TICKS - i) / TICKS))
            for i in range(TICKS + 1)
        ]

    @property
    def first(self):
        return self.points[0] if self.points else None

    @property
    def last(self):
        return self.points[-1] if self.points else None

    @property
    def change(self) -> int:
        return self.last.healthy - self.first.healthy if self.points else 0

    @property
    def this_week(self) -> int:
        return self.points[-1].healthy - self.points[-2].healthy if len(self.points) > 1 else 0
