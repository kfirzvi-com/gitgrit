from __future__ import annotations

from datetime import datetime

from app.application.delivery.source_unavailable import SourceUnavailable


class RateLimited(SourceUnavailable):
    """The platform's API allowance is nearly spent; syncing waits for it to
    reset rather than leave nothing for standard runs."""

    def __init__(self, resets_at: datetime):
        self.resets_at = resets_at
        super().__init__(
            f"Paused to stay under GitHub's rate limit: syncing resumes after {resets_at:%H:%M} UTC."
        )
