from __future__ import annotations

from typing import Protocol

from app.domain.delivery import PendingCommits


class RepositoryActivity(Protocol):
    """What a project's repository says beyond deployments."""

    def pending_commits(self, deployed_sha: str, branch: str) -> PendingCommits | None:
        """Commits on ``branch`` that ``deployed_sha`` lacks, or None when
        the platform cannot tell. Raises ``SourceUnavailable`` when the
        token may not read them."""
        ...
