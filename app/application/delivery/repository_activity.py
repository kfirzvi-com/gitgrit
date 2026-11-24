from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.delivery import PendingCommits, PullRequestFacts, ShippedCommit


class RepositoryActivity(Protocol):
    """What a project's repository says beyond deployments. Each method
    raises ``SourceUnavailable`` when the token may not read it."""

    def pending_commits(self, deployed_sha: str, branch: str) -> PendingCommits | None:
        """Commits on ``branch`` that ``deployed_sha`` lacks, or None when
        the platform cannot tell."""
        ...

    def open_pull_requests(self) -> list[PullRequestFacts]:
        """Every pull request open now, however old."""
        ...

    def pull_requests_updated_since(self, since: datetime) -> list[PullRequestFacts]:
        """Pull requests opened, changed, merged or closed since ``since``."""
        ...

    def commits_between(self, base_sha: str, head_sha: str) -> list[ShippedCommit] | None:
        """The commits ``head_sha`` has and ``base_sha`` does not, or None
        when the platform cannot tell (one of them is gone)."""
        ...
