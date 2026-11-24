from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BarTip:
    """What a delivery speed bar says when hovered or focused: its reading in
    full, what that reading means, and the scale it is read against."""

    reading: str
    meaning: str = ""
    scale: str = ""
