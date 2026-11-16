"""Backdated, synthetic deployment history for the demo projects, so the
delivery card has a quarter of data to show before the demo repositories'
scheduled deliveries have built one up for real.

Each demo project gets the strategy and cadence its repository's
``simulate-delivery.yml`` workflow follows, one per DORA tier. Seeded rows
are marked (``seed-`` external ids) and replaced on every run; real
deployments found by a refresh are left alone.

    uv run python manage.py seed_deployments            # every demo project found
    uv run python manage.py seed_deployments --clear    # remove seeded rows only
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from app.domain.delivery import DeploymentStrategy
from app.domain.delivery.deployment_frequency import WEEKS
from app.models import DeliverySettings, Deployment, Project

SEED_PREFIX = "seed-"


@dataclass(frozen=True)
class DemoCadence:
    strategy: DeploymentStrategy
    weekdays: tuple[int, ...] = ()  # Monday is 0
    month_days: tuple[int, ...] = ()
    every_other_month: bool = False
    hours: tuple[int, ...] = (12,)
    failure_rate: float = 0.0
    settings: tuple[tuple[str, str], ...] = ()

    def ships_on(self, day) -> bool:
        if self.weekdays:
            return day.weekday() in self.weekdays
        if self.every_other_month and day.month % 2 == 0:
            return False
        return day.day in self.month_days


DEMO_CADENCES = {
    "gitgrit-demo-orders-service": DemoCadence(
        DeploymentStrategy.ENVIRONMENTS, weekdays=(0, 1, 2, 3, 4), hours=(8, 14), failure_rate=1 / 7
    ),
    "gitgrit-demo-api-gateway": DemoCadence(
        DeploymentStrategy.DEPLOY_WORKFLOW,
        weekdays=(1, 3),
        hours=(9,),
        failure_rate=1 / 7,
        settings=(("deploy_workflow", "deploy.yml"),),
    ),
    "gitgrit-demo-web-storefront": DemoCadence(DeploymentStrategy.DEFAULT_BRANCH, weekdays=(2,), hours=(10,)),
    "gitgrit-demo-auth-service": DemoCadence(
        DeploymentStrategy.DEPLOY_BRANCH, month_days=(1, 15), hours=(11,), settings=(("deploy_branch", "production"),)
    ),
    "gitgrit-demo-payments-service": DemoCadence(
        DeploymentStrategy.RELEASE_TAGS, month_days=(1,), every_other_month=True, hours=(12,)
    ),
}


class Command(BaseCommand):
    help = "Seed a quarter of synthetic deployments for the demo projects (one per DORA tier)."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Only remove seeded deployments.")

    def handle(self, *args, clear: bool = False, **options):
        removed, _ = Deployment.objects.filter(external_id__startswith=SEED_PREFIX).delete()
        self.stdout.write(f"Removed {removed} seeded deployments.")
        if clear:
            return
        projects = Project.objects.filter(name__in=DEMO_CADENCES)
        if not projects:
            self.stdout.write("No demo projects in this database; nothing to seed.")
            return
        for project in projects:
            cadence = DEMO_CADENCES[project.name]
            self._configure(project, cadence)
            count = self._seed(project, cadence)
            self.stdout.write(f"{project.tenant.name} / {project.name}: {count} deployments ({cadence.strategy.label}).")

    def _configure(self, project: Project, cadence: DemoCadence) -> None:
        settings, _ = DeliverySettings.objects.get_or_create(project=project)
        settings.strategy = cadence.strategy.value
        settings.detected_strategy = cadence.strategy.value
        for field, value in cadence.settings:
            setattr(settings, field, value)
        settings.save()

    def _seed(self, project: Project, cadence: DemoCadence) -> int:
        chance = random.Random(project.name)
        today = timezone.localdate()
        rows, tag = [], 0
        for offset in range(WEEKS * 7, 0, -1):  # oldest first, up to yesterday
            day = today - timedelta(days=offset)
            if not cadence.ships_on(day):
                continue
            for hour in cadence.hours:
                tag += 1
                deployed_at = timezone.make_aware(datetime.combine(day, time(hour)))
                rows.append(
                    Deployment(
                        project=project,
                        strategy=cadence.strategy.value,
                        external_id=f"{SEED_PREFIX}{day:%Y%m%d}-{hour}",
                        sha=f"{chance.getrandbits(160):040x}",
                        ref=self._ref(project, cadence, tag),
                        environment="production" if cadence.strategy is DeploymentStrategy.ENVIRONMENTS else "",
                        deployed_at=deployed_at,
                        succeeded=chance.random() >= cadence.failure_rate,
                    )
                )
        Deployment.objects.bulk_create(rows, ignore_conflicts=True)
        return len(rows)

    @staticmethod
    def _ref(project: Project, cadence: DemoCadence, number: int) -> str:
        """What a real source would record as the ref: the tag, the deploy
        branch, or the default branch."""
        if cadence.strategy is DeploymentStrategy.RELEASE_TAGS:
            return f"v0.{number // 10}.{number % 10}"
        if cadence.strategy is DeploymentStrategy.DEPLOY_BRANCH:
            return dict(cadence.settings).get("deploy_branch", "production")
        if cadence.strategy is DeploymentStrategy.ENVIRONMENTS:
            return ""
        return project.default_branch
