from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ChangeLeadTime:
    """One change's way to production: when it started (by the chosen
    start), when it ran in production, and, for a pull request, when it was
    ready for review and merged."""

    started_at: datetime
    deployed_at: datetime
    pull_request: int | None = None
    ready_at: datetime | None = None
    merged_at: datetime | None = None

    @property
    def length(self) -> timedelta:
        return max(self.deployed_at - self.started_at, timedelta(0))

    @property
    def review(self) -> timedelta | None:
        """Ready for review to merged."""
        if self.ready_at is None or self.merged_at is None:
            return None
        return max(self.merged_at - self.ready_at, timedelta(0))

    @property
    def waiting(self) -> timedelta | None:
        """Merged to running in production."""
        if self.merged_at is None:
            return None
        return max(self.deployed_at - self.merged_at, timedelta(0))
