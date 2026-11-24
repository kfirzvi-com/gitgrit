from __future__ import annotations

from datetime import datetime

from app.domain.delivery import PendingCommits, PullRequestFacts, ShippedCommit
from app.infrastructure.delivery.github_api import GitHubApi, github_time
from app.infrastructure.delivery.github_not_found import GitHubNotFound
from app.infrastructure.delivery.github_pull_requests import pull_request_facts, slim_pull_request

PULLS = "Pull requests"
# Commits read per deployment at most; a deployment shipping more counts the
# newest ones.
MAX_SHIPPED = 300


class GitHubRepositoryActivity:
    """A GitHub repository's activity beyond deployments: commits waiting to
    ship come from comparing the deployed commit with the branch, pull
    requests from the pulls list, newest change first."""

    def __init__(self, api: GitHubApi):
        self._api = api

    def pending_commits(self, deployed_sha: str, branch: str) -> PendingCommits | None:
        try:
            compared = self._api.get(f"compare/{deployed_sha}...{branch}", slim=_slim_compare)
        except GitHubNotFound:
            # The deployed commit is gone from the repository (a force-push)
            # or the branch is: there is nothing to compare.
            return None
        if not compared["ahead_by"]:
            return PendingCommits(0)
        return PendingCommits(compared["ahead_by"], github_time(compared["oldest"]))

    def open_pull_requests(self) -> list[PullRequestFacts]:
        items = self._api.pages("pulls", {"state": "open", "per_page": 100}, PULLS, slim=slim_pull_request)
        return [pull_request_facts(item) for item in items]

    def pull_requests_updated_since(self, since: datetime) -> list[PullRequestFacts]:
        found = []
        params = {"state": "all", "sort": "updated", "direction": "desc", "per_page": 100}
        for item in self._api.pages("pulls", params, PULLS, slim=slim_pull_request):
            if github_time(item["updated_at"]) < since:
                break
            found.append(pull_request_facts(item))
        return found

    def commits_between(self, base_sha: str, head_sha: str) -> list[ShippedCommit] | None:
        try:
            items = list(self._api.pages(
                f"compare/{base_sha}...{head_sha}", {"per_page": 100}, key="commits", slim=_slim_commit
            ))
        except GitHubNotFound:
            return None
        return [
            ShippedCommit(sha=item["sha"], authored_at=github_time(item["authored_at"]), first_parent_sha=item["parent"])
            for item in items[-MAX_SHIPPED:]
        ]


def _slim_commit(item: dict) -> dict:
    parents = item.get("parents") or []
    return {
        "sha": item["sha"],
        "authored_at": item["commit"]["author"]["date"],
        "parent": parents[0]["sha"] if parents else "",
    }


def _slim_compare(body: dict) -> dict:
    """Only the count and the oldest commit's time: a compare answer lists
    every commit and file, too much to keep."""
    commits = body.get("commits") or []
    oldest = commits[0]["commit"]["committer"]["date"] if commits else None
    return {"ahead_by": body.get("ahead_by", 0), "oldest": oldest}
