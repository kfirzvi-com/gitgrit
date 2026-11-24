from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AttentionItem:
    """One thing on a project that wants a look, and the tab that shows it.
    ``tone`` is the score tone it is drawn in: failed or needs_attention."""

    text: str
    tab: str
    tone: str = "needs_attention"
    detail: str = ""
