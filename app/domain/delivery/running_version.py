from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from app.domain.delivery.deployment_event import DeploymentEvent
from app.domain.delivery.deployment_strategy import DeploymentStrategy

# A ref that reads as a version: v1.2, 1.2.3, v2.0.0-rc.1, 2026.11.24.
_VERSION = re.compile(r"^[vV]?\d+(\.\d+)+([-+][0-9A-Za-z.\-]+)?$")
SHORT_SHA = 7


@dataclass(frozen=True)
class RunningVersion:
    """What runs in production now: the newest deployment that shipped.

    It is named by its version when the deployment says one (a release tag,
    or a deployment of a version-like ref), else by its short commit."""

    sha: str
    deployed_at: datetime
    ref: str = ""
    environment: str = ""
    tagged: bool = False

    @classmethod
    def latest(cls, deployments: Iterable[DeploymentEvent]) -> RunningVersion | None:
        shipped = [deployment for deployment in deployments if deployment.succeeded]
        if not shipped:
            return None
        return cls.of(max(shipped, key=lambda deployment: deployment.deployed_at))

    @classmethod
    def of(cls, deployment: DeploymentEvent) -> RunningVersion:
        """The version a deployment put (or tried to put) in production."""
        return cls(
            sha=deployment.sha,
            deployed_at=deployment.deployed_at,
            ref=deployment.ref,
            environment=deployment.environment,
            tagged=deployment.strategy is DeploymentStrategy.RELEASE_TAGS,
        )

    @property
    def short_sha(self) -> str:
        return self.sha[:SHORT_SHA]

    @property
    def version(self) -> str:
        """The version name, or "" when the deployment does not say one."""
        if self.ref and (self.tagged or _VERSION.match(self.ref)):
            return self.ref
        return ""

    @property
    def label(self) -> str:
        return self.version or self.short_sha
