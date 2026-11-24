"""Backdated, synthetic delivery history for the demo projects: a quarter
of deployments and pull requests, so the Delivery tab, the Projects list and
the dashboard have data to show before the demo repositories' scheduled
deliveries have built it up for real.

Each demo project gets the strategy and cadence its repository's
``simulate-delivery.yml`` workflow follows, one per DORA tier, and a pull
request pace of its own. Seeded rows are marked (``seed-`` deployment ids,
pull request numbers from 9001 with a ``#seed`` url) and replaced on every
run; real ones found by a sync are left alone.

    uv run python manage.py seed_delivery                        # every demo project found
    uv run python manage.py seed_delivery --workspace "Acme"     # only one workspace's
    uv run python manage.py seed_delivery --clear                # remove seeded rows only
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from app.domain.delivery import DeploymentStrategy, PullRequestState
from app.domain.delivery.deployment_frequency import WEEKS
from app.models import DeliverySettings, Deployment, Project, PullRequest

SEED_PREFIX = "seed-"
SEED_PULL_URL = "#seed"
FIRST_SEED_PULL = 9001


@dataclass(frozen=True)
class DemoCadence:
    strategy: DeploymentStrategy
    weekdays: tuple[int, ...] = ()  # Monday is 0
    month_days: tuple[int, ...] = ()
    every_other_month: bool = False
    hours: tuple[int, ...] = (12,)
    failure_rate: float = 0.0
    settings: tuple[tuple[str, str], ...] = ()
    merges_a_week: float = 1.0
    open_now: int = 1

    def ships_on(self, day) -> bool:
        if self.weekdays:
            return day.weekday() in self.weekdays
        if self.every_other_month and day.month % 2 == 0:
            return False
        return day.day in self.month_days


DEMO_CADENCES = {
    "gitgrit-demo-orders-service": DemoCadence(
        DeploymentStrategy.ENVIRONMENTS, weekdays=(0, 1, 2, 3, 4), hours=(8, 14), failure_rate=1 / 7,
        merges_a_week=8, open_now=3,
    ),
    "gitgrit-demo-api-gateway": DemoCadence(
        DeploymentStrategy.DEPLOY_WORKFLOW,
        weekdays=(1, 3),
        hours=(9,),
        failure_rate=1 / 7,
        settings=(("deploy_workflow", "deploy.yml"),),
        merges_a_week=4, open_now=2,
    ),
    "gitgrit-demo-web-storefront": DemoCadence(
        DeploymentStrategy.DEFAULT_BRANCH, weekdays=(2,), hours=(10,), merges_a_week=2, open_now=1
    ),
    "gitgrit-demo-auth-service": DemoCadence(
        DeploymentStrategy.DEPLOY_BRANCH, month_days=(1, 15), hours=(11,), settings=(("deploy_branch", "production"),),
        merges_a_week=1, open_now=4,
    ),
    "gitgrit-demo-payments-service": DemoCadence(
        DeploymentStrategy.RELEASE_TAGS, month_days=(1,), every_other_month=True, hours=(12,),
        merges_a_week=0.5, open_now=2,
    ),
}


class Command(BaseCommand):
    help = "Seed a quarter of synthetic deployments and pull requests for the demo projects (one per DORA tier)."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Only remove seeded rows.")
        parser.add_argument("--workspace", default="", help="Only seed this workspace's demo projects (its name).")

    def handle(self, *args, clear: bool = False, workspace: str = "", **options):
        removed, _ = Deployment.objects.filter(external_id__startswith=SEED_PREFIX).delete()
        pulls, _ = PullRequest.objects.filter(url__endswith=SEED_PULL_URL).delete()
        self.stdout.write(f"Removed {removed} seeded deployments and {pulls} seeded pull requests.")
        if clear:
            return
        projects = Project.objects.filter(name__in=DEMO_CADENCES).select_related("tenant")
        if workspace:
            projects = projects.filter(tenant__name=workspace)
        if not projects:
            self.stdout.write("No demo projects in this database; nothing to seed.")
            return
        for project in projects:
            cadence = DEMO_CADENCES[project.name]
            self._configure(project, cadence)
            count = self._seed(project, cadence)
            pulls = self._seed_pull_requests(project, cadence)
            self.stdout.write(
                f"{project.tenant.name} / {project.name}: {count} deployments ({cadence.strategy.label}), "
                f"{pulls} pull requests."
            )

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

    def _seed_pull_requests(self, project: Project, cadence: DemoCadence) -> int:
        """Merges at the cadence's pace, each open one to four days, plus
        ``open_now`` still open; one in eight is a bot's, one in six closes
        unmerged."""
        chance = random.Random(f"{project.name}-pulls")
        now = timezone.now()
        merges = round(cadence.merges_a_week * WEEKS)
        rows = []
        for index in range(merges + cadence.open_now):
            number = FIRST_SEED_PULL + index
            bot = chance.random() < 1 / 8
            if index < merges:
                closed_at = now - timedelta(days=chance.uniform(0, WEEKS * 7))
                created_at = closed_at - timedelta(days=chance.uniform(0.1, 4))
                merged_at = closed_at if chance.random() >= 1 / 6 else None
                state = PullRequestState.MERGED if merged_at else PullRequestState.CLOSED
            else:
                created_at = now - timedelta(days=chance.uniform(0.5, 20))
                closed_at = merged_at = None
                state = PullRequestState.OPEN
            rows.append(
                PullRequest(
                    project=project,
                    number=number,
                    title=chance.choice(_TITLES_BOT if bot else _TITLES),
                    author="dependabot[bot]" if bot else chance.choice(("demo-dev", "demo-reviewer", "demo-lead")),
                    author_is_bot=bot,
                    url=SEED_PULL_URL,
                    draft=state is PullRequestState.OPEN and chance.random() < 1 / 4,
                    state=state.value,
                    base_ref=project.default_branch,
                    created_at=created_at,
                    updated_at=closed_at or created_at,
                    merged_at=merged_at,
                    closed_at=closed_at,
                )
            )
        PullRequest.objects.bulk_create(rows, ignore_conflicts=True)
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


_TITLES = (
    "Add retry to the payment callback",
    "Tidy the checkout logging",
    "Cache the product lookup",
    "Fix the flaky order test",
    "Move config to environment variables",
    "Raise the request timeout",
    "Document the deploy steps",
    "Split the large handler",
)
_TITLES_BOT = ("Bump requests from 2.32.3 to 2.32.4", "Bump actions/checkout from 4 to 5", "Bump django from 6.0 to 6.0.1")
