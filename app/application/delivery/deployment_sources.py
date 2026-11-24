from __future__ import annotations

from typing import Protocol

from app.application.delivery.deployment_source import DeploymentSource
from app.domain.delivery import DeploymentStrategy


class DeploymentSources(Protocol):
    """One project's deployment sources, one per strategy its platform
    supports."""

    def for_strategy(self, strategy: DeploymentStrategy) -> DeploymentSource:
        """The source for ``strategy``. Raises ``SourceUnavailable`` when the
        project's platform cannot tell deployments that way."""
        ...
