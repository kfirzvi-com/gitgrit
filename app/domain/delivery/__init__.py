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
* ``RunningVersion`` — what runs in production now;
* ``PendingCommits`` — commits on the default branch not shipped yet;
* ``PullRequestFacts`` / ``PullRequestState`` — one pull request;
* ``PullRequestFlow`` / ``WeeklyPullRequests`` — merges per week and what
  stays open, over the same weeks;
* ``DeliveryTotals`` — a workspace's delivery, summed over its projects;
* ``SyncPolicy`` — how often delivery data is read from the platform;
* ``RateLimit`` — what is left of a token's API allowance.
"""
from app.domain.delivery.delivery_totals import DeliveryTotals
from app.domain.delivery.deployment_event import DeploymentEvent
from app.domain.delivery.deployment_frequency import DeploymentFrequency
from app.domain.delivery.deployment_strategy import DeploymentStrategy
from app.domain.delivery.dora_tier import DoraTier
from app.domain.delivery.pending_commits import PendingCommits
from app.domain.delivery.production_environment import ProductionEnvironment
from app.domain.delivery.pull_request_facts import PullRequestFacts
from app.domain.delivery.pull_request_flow import PullRequestFlow
from app.domain.delivery.pull_request_state import PullRequestState
from app.domain.delivery.rate_limit import RateLimit
from app.domain.delivery.running_version import RunningVersion
from app.domain.delivery.sync_policy import SyncPolicy
from app.domain.delivery.weekly_deployments import WeeklyDeployments
from app.domain.delivery.weekly_pull_requests import WeeklyPullRequests

__all__ = [
    "DeliveryTotals",
    "DeploymentEvent",
    "DeploymentFrequency",
    "DeploymentStrategy",
    "DoraTier",
    "PendingCommits",
    "ProductionEnvironment",
    "PullRequestFacts",
    "PullRequestFlow",
    "PullRequestState",
    "RateLimit",
    "RunningVersion",
    "SyncPolicy",
    "WeeklyDeployments",
    "WeeklyPullRequests",
]
