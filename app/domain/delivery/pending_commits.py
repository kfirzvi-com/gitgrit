from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PendingCommits:
    """Commits on the default branch that have not reached production yet:
    how many, and since when the oldest has been waiting."""

    count: int
    oldest_at: datetime | None = None

    def __post_init__(self):
        if self.count < 0:
            raise ValueError("A commit count cannot be negative.")
        if self.count and self.oldest_at is None:
            raise ValueError("Waiting commits need the oldest one's time.")

    @property
    def any(self) -> bool:
        return self.count > 0
