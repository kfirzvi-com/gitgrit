from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.delivery.shipped_commit import ShippedCommit


@dataclass(frozen=True)
class Shipment:
    """A successful deployment with the commits it brought to production:
    those its commit has and the previous deployment's did not."""

    head_sha: str
    deployed_at: datetime
    commits: tuple[ShippedCommit, ...]

    def mainline(self) -> list[ShippedCommit]:
        """The commits on the deployed branch's own line, newest first:
        from the deployed commit back through first parents. A pull request
        merged with a merge commit adds that commit here; its own commits
        sit off the line. A squash or a direct push is on the line."""
        by_sha = {commit.sha: commit for commit in self.commits}
        line, sha = [], self.head_sha
        while sha in by_sha:
            commit = by_sha.pop(sha)
            line.append(commit)
            sha = commit.first_parent_sha
        return line
