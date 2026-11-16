from __future__ import annotations

from datetime import datetime

from app.domain.delivery import DeploymentEvent, DeploymentStrategy, ProductionEnvironment
from app.infrastructure.delivery.github_api import GitHubApi, github_time

_FAILED = {"failure", "error"}


class GitHubEnvironmentDeployments:
    """Deployments GitHub recorded to a production environment (a GitHub
    Actions job with ``environment:`` records one). A deployment counts once
    it reaches ``success``, at that time; one that only failed counts as a
    failed deployment; one still running is left for the next refresh."""

    strategy = DeploymentStrategy.ENVIRONMENTS

    def __init__(self, api: GitHubApi, production: ProductionEnvironment):
        self._api = api
        self._production = production

    def find(self, since: datetime) -> list[DeploymentEvent]:
        events = []
        for deployment in self._api.pages("deployments", {"per_page": 100}, permission="Deployments"):
            if github_time(deployment["created_at"]) < since:
                break  # newest first
            if not self._production.matches(deployment["environment"]):
                continue
            event = self._event(deployment)
            if event:
                events.append(event)
        return events

    def _event(self, deployment: dict) -> DeploymentEvent | None:
        statuses = self._api.get(
            f"deployments/{deployment['id']}/statuses", {"per_page": 100}, permission="Deployments"
        )
        oldest_first = list(reversed(statuses))
        success = next((s for s in oldest_first if s["state"] == "success"), None)
        failure = next((s for s in oldest_first if s["state"] in _FAILED), None)
        settled = success or failure
        if not settled:
            return None
        return DeploymentEvent(
            strategy=self.strategy,
            external_id=str(deployment["id"]),
            sha=deployment["sha"],
            deployed_at=github_time(settled["created_at"]),
            succeeded=success is not None,
            environment=deployment["environment"],
            ref=deployment.get("ref", ""),
        )
