from __future__ import annotations

from app.application.delivery import DeploymentSource, SourceUnavailable
from app.domain.delivery import DeploymentStrategy
from app.infrastructure.delivery.reported_deployments import ReportedDeployments


class UnsupportedPlatformSources:
    """Deployment sources for a platform GitGrit cannot read deployments
    from yet (GitLab, uploaded artifacts): only reported deployments work."""

    def __init__(self, platform_label: str):
        self._platform_label = platform_label

    def for_strategy(self, strategy: DeploymentStrategy) -> DeploymentSource:
        if strategy is DeploymentStrategy.REPORTED:
            return ReportedDeployments()
        raise SourceUnavailable(
            f"GitGrit can't read deployments from {self._platform_label} yet; "
            "report them to the GitGrit API instead."
        )
