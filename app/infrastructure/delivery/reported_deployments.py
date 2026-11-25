from __future__ import annotations

from datetime import datetime

from app.domain.delivery import DeploymentEvent, DeploymentStrategy


class ReportedDeployments:
    """Deployments a pipeline reports to the GitGrit API arrive on their own,
    so there is nothing to look for: refreshing keeps what was reported."""

    strategy = DeploymentStrategy.REPORTED

    def find(self, since: datetime) -> list[DeploymentEvent]:
        return []
