from __future__ import annotations

import requests

from app.domain.delivery import PendingCommits
from app.infrastructure.delivery.github_api import GitHubApi, github_time


class GitHubRepositoryActivity:
    """A GitHub repository's activity beyond deployments: commits waiting to
    ship come from comparing the deployed commit with the branch."""

    def __init__(self, api: GitHubApi):
        self._api = api

    def pending_commits(self, deployed_sha: str, branch: str) -> PendingCommits | None:
        try:
            compared = self._api.get(f"compare/{deployed_sha}...{branch}", slim=_slim_compare)
        except requests.HTTPError as error:
            # The deployed commit is gone from the repository (a force-push)
            # or the branch is: there is nothing to compare.
            if error.response is not None and error.response.status_code in (404, 422):
                return None
            raise
        if not compared["ahead_by"]:
            return PendingCommits(0)
        return PendingCommits(compared["ahead_by"], github_time(compared["oldest"]))


def _slim_compare(body: dict) -> dict:
    """Only the count and the oldest commit's time: a compare answer lists
    every commit and file, too much to keep."""
    commits = body.get("commits") or []
    oldest = commits[0]["commit"]["committer"]["date"] if commits else None
    return {"ahead_by": body.get("ahead_by", 0), "oldest": oldest}
