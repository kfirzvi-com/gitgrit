from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.delivery.deployment_strategy import DeploymentStrategy


@dataclass(frozen=True)
class DeploymentEvent:
    """One deployment a strategy found: which commit shipped, when, where to,
    and whether it worked. ``external_id`` is the source's own id for it (a
    deployment id, a tag name, a run id, a push id), so finding it again does
    not record it twice."""

    strategy: DeploymentStrategy
    external_id: str
    sha: str
    deployed_at: datetime
    succeeded: bool = True
    environment: str = ""
    ref: str = ""

    def __post_init__(self):
        if self.strategy is DeploymentStrategy.AUTO:
            raise ValueError("A deployment is found by a concrete strategy, not AUTO.")
        if not self.external_id:
            raise ValueError("A deployment needs the source's id for it.")
        if self.deployed_at.tzinfo is None:
            raise ValueError("deployed_at must be timezone-aware.")
