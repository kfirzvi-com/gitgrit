from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BarTip:
    """What a delivery speed bar says when hovered or focused: its reading in
    full, what that reading means, the scale it is read against, and how it
    is counted across the workspace."""

    reading: str
    meaning: str = ""
    scale: str = ""
    how: str = ""
