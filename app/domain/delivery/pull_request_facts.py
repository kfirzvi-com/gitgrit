from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.delivery.pull_request_state import PullRequestState


@dataclass(frozen=True)
class PullRequestFacts:
    """One pull request as its platform reports it. Drafts and bot pull
    requests count like any other. ``merge_commit_sha`` is the commit its
    merge put on the base branch; ``ready_at`` when it was ready for review
    (None: not known, or still a draft)."""

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
    merge_commit_sha: str = ""
    ready_at: datetime | None = None

    def __post_init__(self):
        if self.number < 1:
            raise ValueError("A pull request number starts at 1.")
        for moment in (self.created_at, self.updated_at, self.merged_at, self.closed_at, self.ready_at):
            if moment is not None and moment.tzinfo is None:
                raise ValueError("Pull request times must be timezone-aware.")

    def ready_since(self, stored_draft: bool | None, stored_ready_at: datetime | None) -> datetime | None:
        """When it became ready for review, given what was stored before
        (``stored_draft`` None: never seen). A known time is kept; a pull
        request seen leaving draft became ready at that change; one never
        seen as a draft was ready when opened."""
        if stored_ready_at is not None:
            return stored_ready_at
        if self.ready_at is not None:
            return self.ready_at
        if self.draft:
            return None
        return self.updated_at if stored_draft else self.created_at

    @property
    def state(self) -> PullRequestState:
        if self.merged_at is not None:
            return PullRequestState.MERGED
        if self.closed_at is not None:
            return PullRequestState.CLOSED
        return PullRequestState.OPEN
