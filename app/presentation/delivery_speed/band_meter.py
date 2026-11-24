from __future__ import annotations

from typing import Sequence

from app.presentation.delivery_speed.band import Band


class BandMeter:
    """Where a value falls among bands, drawn as a bar of equal parts, worst
    on the left, best on the right, with a marker at the value.

    ``edges`` are the band boundaries from the worst end to the best end,
    one more than ``bands``; they run either way (deploys a week rise
    towards the best, a lead time falls). Within its band a value sits in
    proportion; past either end it sits at that end."""

    def __init__(self, value: float | None, edges: Sequence[float], bands: Sequence[Band]):
        if len(edges) != len(bands) + 1:
            raise ValueError("A band meter needs one more edge than bands.")
        self.value = value
        self.edges = tuple(edges)
        self.bands = tuple(bands)

    @property
    def known(self) -> bool:
        return self.value is not None

    @property
    def fraction(self) -> float:
        """0 at the worst end, 1 at the best."""
        if self.value is None:
            return 0.0
        rising = self.edges[-1] > self.edges[0]
        count = len(self.bands)
        for index in range(count):
            worse, better = self.edges[index], self.edges[index + 1]
            low, high = (worse, better) if rising else (better, worse)
            if low <= self.value <= high:
                return (index + abs(self.value - worse) / abs(better - worse)) / count
        past_best = self.value > self.edges[-1] if rising else self.value < self.edges[-1]
        return 1.0 if past_best else 0.0

    @property
    def marker(self) -> float:
        """The marker's place along the bar, in percent."""
        return round(100 * self.fraction, 2)

    @property
    def band(self) -> Band | None:
        """The band the value falls in."""
        if self.value is None:
            return None
        return self.bands[min(int(self.fraction * len(self.bands)), len(self.bands) - 1)]

    @property
    def width(self) -> float:
        """Each band's share of the bar, in percent."""
        return round(100 / len(self.bands), 4)
