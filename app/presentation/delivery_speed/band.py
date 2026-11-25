from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Band:
    """One part of a band meter: its name and the colour class it is drawn
    in (a DaisyUI background: bg-error, bg-warning, bg-info, bg-success)."""

    label: str
    css: str
