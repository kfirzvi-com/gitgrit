from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import reduce
from operator import or_
from typing import Iterable

from django.db.models import Q
from django.utils import timezone

from app.application.delivery.deployment_refresh import LOOKBACK
from app.application.delivery.lead_times import LeadTimes
from app.domain.delivery import DeploymentFrequency, LeadTime, LeadTimeStart, PullRequestFlow, RunningVersion
from app.domain.delivery.deployment_frequency import WEEKS
from app.models import DeliverySettings, Deployment, Project, PullRequest


@dataclass(frozen=True)
class DeliverySummary:
    """One project's delivery at a glance, for pages that list many
    projects: what runs in production, how often it ships, how long its
    changes take to get there, and how its pull requests flow. Read in six
    queries however many projects there are."""

    running: RunningVersion | None
    frequency: DeploymentFrequency
    pull_requests: PullRequestFlow
    lead_time: LeadTime
    synced: bool = False

    @classmethod
    def for_projects(cls, projects: Iterable[Project], now: datetime | None = None) -> dict:
        """A summary per project, keyed by project id."""
        ids = [project.pk for project in projects]
        now = timezone.localtime(now or timezone.now())
        settings = {s.project_id: s for s in DeliverySettings.objects.filter(project_id__in=ids)}
        events = cls._deployments(settings, now)
        pulls = defaultdict(list)
        window_start = now - timedelta(weeks=WEEKS)
        for pr in PullRequest.objects.filter(project_id__in=ids).filter(
            Q(closed_at__isnull=True) | Q(closed_at__gte=window_start)
        ):
            pulls[pr.project_id].append(pr.facts)
        lead_times = LeadTimes.for_settings(settings, now)
        return {
            pk: cls(
                running=RunningVersion.latest(events[pk]),
                frequency=DeploymentFrequency.of(events[pk], now.date(), tz=now.tzinfo),
                pull_requests=PullRequestFlow.of(pulls[pk], now.date(), tz=now.tzinfo, now=now),
                lead_time=lead_times.get(pk) or LeadTime.of([], [], now.date(), LeadTimeStart.COMMIT, tz=now.tzinfo),
                synced=pk in settings and settings[pk].refreshed_at is not None,
            )
            for pk in ids
        }

    @staticmethod
    def _deployments(settings: dict, now: datetime) -> defaultdict:
        """Each project's deployments by the strategy it counts with."""
        events = defaultdict(list)
        by_strategy = defaultdict(list)
        for project_id, setting in settings.items():
            if strategy := setting.strategy_in_use:
                by_strategy[strategy].append(project_id)
        if not by_strategy:
            return events
        matches = reduce(or_, (Q(strategy=s, project_id__in=pks) for s, pks in by_strategy.items()))
        for deployment in Deployment.objects.filter(matches, deployed_at__gte=now - LOOKBACK):
            events[deployment.project_id].append(deployment.event)
        return events
