from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.delivery.pull_request_state import PullRequestState


@dataclass(frozen=True)
class PullRequestFacts:
    """One pull request as its platform reports it. Drafts and bot pull
    requests count like any other."""

    number: int
    title: str
    author: str
    url: str
    created_at: datetime
    updated_at: datetime
    draft: bool = False
    author_is_bot: bool = False
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    base_ref: str = ""

    def __post_init__(self):
        if self.number < 1:
            raise ValueError("A pull request number starts at 1.")
        for moment in (self.created_at, self.updated_at, self.merged_at, self.closed_at):
            if moment is not None and moment.tzinfo is None:
                raise ValueError("Pull request times must be timezone-aware.")

    @property
    def state(self) -> PullRequestState:
        if self.merged_at is not None:
            return PullRequestState.MERGED
        if self.closed_at is not None:
            return PullRequestState.CLOSED
        return PullRequestState.OPEN
