from __future__ import annotations

from app.application.delivery import DeploymentSource
from app.domain.delivery import DeploymentStrategy
from app.infrastructure.delivery.github_api import GitHubApi
from app.infrastructure.delivery.github_branch_pushes import GitHubBranchPushes
from app.infrastructure.delivery.github_environment_deployments import GitHubEnvironmentDeployments
from app.infrastructure.delivery.github_release_tags import GitHubReleaseTags
from app.infrastructure.delivery.github_workflow_runs import GitHubWorkflowRuns
from app.infrastructure.delivery.reported_deployments import ReportedDeployments
from app.infrastructure.platform_client import get_platform_client
from app.models import DeliverySettings, Project


class GitHubDeploymentSources:
    """A GitHub repository's deployment sources, configured from the
    project's delivery settings."""

    def __init__(self, project: Project, settings: DeliverySettings):
        client = get_platform_client(project.platform_connection)
        self._api = GitHubApi(client.base_url, client.token, project.full_path)
        self._project = project
        self._settings = settings

    def for_strategy(self, strategy: DeploymentStrategy) -> DeploymentSource:
        settings, branch = self._settings, self._project.default_branch
        if strategy is DeploymentStrategy.ENVIRONMENTS:
            return GitHubEnvironmentDeployments(self._api, settings.production)
        if strategy is DeploymentStrategy.RELEASE_TAGS:
            return GitHubReleaseTags(self._api, settings.release_tag_pattern)
        if strategy is DeploymentStrategy.DEPLOY_WORKFLOW:
            return GitHubWorkflowRuns(self._api, settings.deploy_workflow, branch)
        if strategy is DeploymentStrategy.DEPLOY_BRANCH:
            return GitHubBranchPushes(self._api, strategy, settings.deploy_branch)
        if strategy is DeploymentStrategy.DEFAULT_BRANCH:
            return GitHubBranchPushes(self._api, strategy, branch)
        if strategy is DeploymentStrategy.REPORTED:
            return ReportedDeployments()
        raise ValueError(f"No source for {strategy}")
