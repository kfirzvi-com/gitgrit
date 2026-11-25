from __future__ import annotations

from enum import StrEnum


class PullRequestState(StrEnum):
    """Where a pull request stands: still open, merged, or closed unmerged."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(state.value, state.value.title()) for state in cls]
