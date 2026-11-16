from __future__ import annotations

from datetime import datetime

from app.domain.delivery import DeploymentEvent, DeploymentStrategy
from app.infrastructure.delivery.github_api import GitHubApi, github_time

_SHIPPING = {"push", "force_push", "pr_merge", "merge_queue_merge"}


class GitHubBranchPushes:
    """Each push to a branch is a deployment: the deploy branch (such as
    ``production``) or, as the fallback, the default branch. Read from the
    repository's activity, so a push of several commits counts once and a
    merged pull request counts as the push it is."""

    def __init__(self, api: GitHubApi, strategy: DeploymentStrategy, branch: str):
        self.strategy = strategy
        self._api = api
        self._branch = branch

    def find(self, since: datetime) -> list[DeploymentEvent]:
        params = {"ref": f"refs/heads/{self._branch}", "time_period": "year", "per_page": 100}
        events = []
        for activity in self._api.pages("activity", params):
            pushed_at = github_time(activity["timestamp"])
            if pushed_at < since:
                break  # newest first
            if activity["activity_type"] not in _SHIPPING:
                continue
            events.append(
                DeploymentEvent(
                    strategy=self.strategy,
                    external_id=str(activity["id"]),
                    sha=activity["after"],
                    deployed_at=pushed_at,
                    ref=self._branch,
                )
            )
        return events
