from __future__ import annotations

import math

CENTER = 100  # every gauge is drawn in a 200 x 200 viewBox around (100, 100)


class Speedometer:
    """A round cockpit gauge: a value against a full scale, as the arc, the
    share of it filled, where the needle points and the tick marks. The arc
    runs clockwise from ``start`` degrees (maths angles: 0 is right, 90 up)
    for ``sweep`` degrees: a speedometer is 225° round to -45°; a fuel gauge
    a shallow arc across the top."""

    def __init__(self, value, full_scale, *, start=225, sweep=270, radius=76, needle=58, ticks=11):
        self.value = value
        self.full_scale = max(full_scale, value, 1)
        self.start, self.sweep, self.radius, self.needle_length, self.tick_count = start, sweep, radius, needle, ticks

    def _point(self, angle_deg, r):
        a = math.radians(angle_deg)
        return round(CENTER + r * math.cos(a), 1), round(CENTER - r * math.sin(a), 1)

    @property
    def fraction(self) -> float:
        return self.value / self.full_scale

    @property
    def share(self) -> float:
        """Percent of the arc filled."""
        return round(100 * self.fraction, 2)

    @property
    def arc_path(self) -> str:
        x0, y0 = self._point(self.start, self.radius)
        x1, y1 = self._point(self.start - self.sweep, self.radius)
        large = 1 if self.sweep > 180 else 0
        return f"M {x0} {y0} A {self.radius} {self.radius} 0 {large} 1 {x1} {y1}"

    @property
    def needle(self) -> tuple[float, float]:
        return self._point(self.start - self.sweep * self.fraction, self.needle_length)

    @property
    def needle_x(self):
        return self.needle[0]

    @property
    def needle_y(self):
        return self.needle[1]

    @property
    def ticks(self) -> list[tuple[float, float, float, float]]:
        """(x1, y1, x2, y2) of each tick mark just outside the arc."""
        marks = []
        for i in range(self.tick_count):
            angle = self.start - self.sweep * i / (self.tick_count - 1)
            marks.append(self._point(angle, self.radius + 8) + self._point(angle, self.radius + 14))
        return marks
