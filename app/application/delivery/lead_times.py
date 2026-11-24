from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from functools import reduce
from operator import or_

from django.db.models import Prefetch, Q

from app.application.delivery.deployment_refresh import LOOKBACK
from app.domain.delivery import LeadTime, LeadTimeStart, Shipment
from app.models import DeliverySettings, Deployment, PullRequest, ShippedCommit


class LeadTimes:
    """Lead time for changes of one or many projects, each from its own
    start, read in three queries: their shipments, the commits in them, and
    the pull requests those commits merged."""

    @staticmethod
    def for_settings(settings: dict, now: datetime) -> dict:
        """A ``LeadTime`` per project id in ``settings`` (project id →
        ``DeliverySettings``) that has a strategy in use."""
        by_strategy = defaultdict(list)
        for project_id, setting in settings.items():
            if strategy := setting.strategy_in_use:
                by_strategy[strategy].append(project_id)
        if not by_strategy:
            return {}
        matches = reduce(or_, (Q(strategy=s, project_id__in=pks) for s, pks in by_strategy.items()))
        deployments = Deployment.objects.filter(matches, succeeded=True, deployed_at__gte=now - LOOKBACK).prefetch_related(
            Prefetch("shipped_commits", queryset=ShippedCommit.objects.only("deployment_id", "sha", "authored_at", "first_parent_sha"))
        )
        shipments, shas = defaultdict(list), set()
        for deployment in deployments:
            commits = tuple(commit.facts for commit in deployment.shipped_commits.all())
            shas.update(commit.sha for commit in commits)
            shipments[deployment.project_id].append(Shipment(deployment.sha, deployment.deployed_at, commits))
        pulls = defaultdict(list)
        if shas:
            for pr in PullRequest.objects.filter(project_id__in=list(shipments), merge_commit_sha__in=shas):
                pulls[pr.project_id].append(pr.facts)
        return {
            project_id: LeadTime.of(
                shipments[project_id],
                pulls[project_id],
                now.date(),
                LeadTimeStart(setting.lead_time_start),
                tz=now.tzinfo,
            )
            for project_id, setting in settings.items()
            if setting.strategy_in_use
        }

    @classmethod
    def for_project(cls, setting: DeliverySettings, now: datetime) -> LeadTime:
        return cls.for_settings({setting.project_id: setting}, now).get(setting.project_id) or LeadTime.of(
            [], [], now.date(), LeadTimeStart(setting.lead_time_start), tz=now.tzinfo
        )
