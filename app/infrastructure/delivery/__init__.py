"""Deployment sources: adapters behind ``app.application.delivery``'s
``DeploymentSources`` port, one per strategy a platform supports."""
from app.application.delivery import DeploymentSources, RepositoryActivity
from app.domain.models import Platform
from app.infrastructure.delivery.github_api import GitHubApi
from app.infrastructure.delivery.github_deployment_sources import GitHubDeploymentSources
from app.infrastructure.delivery.github_repository_activity import GitHubRepositoryActivity
from app.infrastructure.delivery.unsupported_platform_sources import UnsupportedPlatformSources
from app.infrastructure.delivery.unsupported_repository_activity import UnsupportedRepositoryActivity
from app.infrastructure.platform_client import get_platform_client
from app.models import DeliverySettings, Project


def deployment_sources_for(project: Project, settings: DeliverySettings) -> DeploymentSources:
    """The deployment sources for a project's platform."""
    if project.platform == Platform.GITHUB:
        return GitHubDeploymentSources(project, settings)
    return UnsupportedPlatformSources(Platform(project.platform).label)


def repository_activity_for(project: Project) -> RepositoryActivity:
    """What a project's repository says beyond deployments, for its platform."""
    if project.platform == Platform.GITHUB:
        client = get_platform_client(project.platform_connection)
        return GitHubRepositoryActivity(GitHubApi(client.base_url, client.token, project.full_path))
    return UnsupportedRepositoryActivity()


__all__ = [
    "GitHubDeploymentSources",
    "GitHubRepositoryActivity",
    "UnsupportedPlatformSources",
    "UnsupportedRepositoryActivity",
    "deployment_sources_for",
    "repository_activity_for",
]
