from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ActivityItem:
    """One recent event on a project: a deployment, a merged pull request
    or a standard's result. ``tone`` colours its mark (healthy, failed,
    needs_attention, or "" for neutral)."""

    kind: str
    text: str
    at: datetime
    tab: str
    url: str = ""
    tone: str = ""
