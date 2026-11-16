"""Deployment sources: adapters behind ``app.application.delivery``'s
``DeploymentSources`` port, one per strategy a platform supports."""
from app.application.delivery import DeploymentSources
from app.domain.models import Platform
from app.infrastructure.delivery.github_deployment_sources import GitHubDeploymentSources
from app.infrastructure.delivery.unsupported_platform_sources import UnsupportedPlatformSources
from app.models import DeliverySettings, Project


def deployment_sources_for(project: Project, settings: DeliverySettings) -> DeploymentSources:
    """The deployment sources for a project's platform."""
    if project.platform == Platform.GITHUB:
        return GitHubDeploymentSources(project, settings)
    return UnsupportedPlatformSources(Platform(project.platform).label)


__all__ = ["GitHubDeploymentSources", "UnsupportedPlatformSources", "deployment_sources_for"]
