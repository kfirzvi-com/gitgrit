from __future__ import annotations

from datetime import datetime

import requests

from app.application.delivery import SourceUnavailable
from app.domain.delivery import DeploymentEvent, DeploymentStrategy
from app.infrastructure.delivery.github_api import GitHubApi, github_time

_FAILED = {"failure", "timed_out"}


class GitHubWorkflowRuns:
    """Each completed run of the deploy workflow on the default branch is a
    deployment, successful or failed. Cancelled and skipped runs shipped
    nothing and tried nothing, so they do not count."""

    strategy = DeploymentStrategy.DEPLOY_WORKFLOW

    def __init__(self, api: GitHubApi, workflow: str, branch: str):
        self._api = api
        self._workflow = workflow.strip().split("/")[-1]
        self._branch = branch

    def find(self, since: datetime) -> list[DeploymentEvent]:
        if not self._workflow:
            raise SourceUnavailable(
                "Name the deploy workflow file (such as deploy.yml) in the project's delivery settings."
            )
        params = {
            "branch": self._branch,
            "status": "completed",
            "created": f">={since:%Y-%m-%d}",
            "per_page": 100,
        }
        try:
            runs = list(
                self._api.pages(
                    f"actions/workflows/{self._workflow}/runs", params, permission="Actions", key="workflow_runs"
                )
            )
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                raise SourceUnavailable(f"The repository has no workflow named {self._workflow}.") from error
            raise
        return [self._event(run) for run in runs if run["conclusion"] == "success" or run["conclusion"] in _FAILED]

    def _event(self, run: dict) -> DeploymentEvent:
        return DeploymentEvent(
            strategy=self.strategy,
            external_id=str(run["id"]),
            sha=run["head_sha"],
            deployed_at=github_time(run["updated_at"]),
            succeeded=run["conclusion"] == "success",
            ref=self._branch,
        )
