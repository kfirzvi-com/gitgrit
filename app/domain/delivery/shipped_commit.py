from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ShippedCommit:
    """A commit a deployment shipped: when it was written (its author date,
    which a rebase keeps) and its first parent, the line of the branch it
    landed on."""

    sha: str
    authored_at: datetime
    first_parent_sha: str = ""

    def __post_init__(self):
        if self.authored_at.tzinfo is None:
            raise ValueError("authored_at must be timezone-aware.")
