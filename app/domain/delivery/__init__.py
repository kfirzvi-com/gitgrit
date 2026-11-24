"""Delivery: how a project ships to production, for the DORA metrics.

Pure Python (no Django): the vocabulary and rules every layer shares.

* ``DeploymentStrategy`` — which signal counts as a deployment (production
  environments, release tags, a deploy workflow, a deploy branch, the default
  branch, or reported through the API), or detect one;
* ``ProductionEnvironment`` — which environment names count as production;
* ``DeploymentEvent`` — one deployment a strategy found;
* ``DeploymentFrequency`` / ``WeeklyDeployments`` — changes shipped per week
  over the last quarter;
* ``DoraTier`` — the DORA band that frequency falls in;
* ``SyncPolicy`` — how often delivery data is read from the platform;
* ``RateLimit`` — what is left of a token's API allowance.
"""
from app.domain.delivery.deployment_event import DeploymentEvent
from app.domain.delivery.deployment_frequency import DeploymentFrequency
from app.domain.delivery.deployment_strategy import DeploymentStrategy
from app.domain.delivery.dora_tier import DoraTier
from app.domain.delivery.production_environment import ProductionEnvironment
from app.domain.delivery.rate_limit import RateLimit
from app.domain.delivery.sync_policy import SyncPolicy
from app.domain.delivery.weekly_deployments import WeeklyDeployments

__all__ = [
    "DeploymentEvent",
    "DeploymentFrequency",
    "DeploymentStrategy",
    "DoraTier",
    "ProductionEnvironment",
    "RateLimit",
    "SyncPolicy",
    "WeeklyDeployments",
]
