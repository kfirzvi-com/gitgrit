from __future__ import annotations

from datetime import datetime

from app.domain.delivery import PendingCommits, PullRequestFacts


class UnsupportedRepositoryActivity:
    """A platform GitGrit cannot read delivery activity from yet: nothing is
    known, and nothing is wrong."""

    def pending_commits(self, deployed_sha: str, branch: str) -> PendingCommits | None:
        return None

    def open_pull_requests(self) -> list[PullRequestFacts]:
        return []

    def pull_requests_updated_since(self, since: datetime) -> list[PullRequestFacts]:
        return []
