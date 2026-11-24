from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WeeklyDeployments:
    """One week of a deployment-frequency window: the week's first day, how
    many changes shipped and on how many different days."""

    starts: date
    deployments: int
    deploy_days: int
