from __future__ import annotations

from app.domain.delivery import PendingCommits


class UnsupportedRepositoryActivity:
    """A platform GitGrit cannot read delivery activity from yet: nothing is
    known, and nothing is wrong."""

    def pending_commits(self, deployed_sha: str, branch: str) -> PendingCommits | None:
        return None
