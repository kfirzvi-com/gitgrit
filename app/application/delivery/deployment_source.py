from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.delivery import DeploymentEvent, DeploymentStrategy


class DeploymentSource(Protocol):
    """Finds one project's deployments by one strategy. Adapters in
    ``app.infrastructure.delivery`` read them from the Git platform."""

    strategy: DeploymentStrategy

    def find(self, since: datetime) -> list[DeploymentEvent]:
        """Every deployment from ``since`` on, failed ones included. Raises
        ``SourceUnavailable`` when the platform will not say."""
        ...
