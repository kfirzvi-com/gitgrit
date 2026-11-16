"""Delivery use cases: refreshing a project's deployments (detection,
recording, problems) and the report the Delivery tab shows."""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app.application.delivery import DeliveryReport, DeploymentRefresh, DeploymentRefreshRequest, SourceUnavailable
from app.domain.delivery import DeploymentEvent, DeploymentStrategy, DoraTier
from app.models import DeliverySettings, Deployment, Project

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def event(strategy, external_id, days_ago=1, sha=None, succeeded=True):
    return DeploymentEvent(
        strategy=strategy,
        external_id=external_id,
        sha=sha or f"sha-{external_id}",
        deployed_at=NOW - timedelta(days=days_ago),
        succeeded=succeeded,
    )


class FakeSource:
    def __init__(self, strategy, events=(), unavailable=""):
        self.strategy = strategy
        self.events = list(events)
        self.unavailable = unavailable
        self.since = None

    def find(self, since):
        self.since = since
        if self.unavailable:
            raise SourceUnavailable(self.unavailable)
        return self.events


class FakeSources:
    def __init__(self, *sources):
        self.by_strategy = {source.strategy: source for source in sources}

    def for_strategy(self, strategy):
        return self.by_strategy.get(strategy) or FakeSource(strategy)


class DeploymentRefreshTests(TestCase):
    def setUp(self):
        self.project = baker.make(Project)

    def refresh(self, *sources):
        fakes = FakeSources(*sources)
        return DeploymentRefresh(lambda project, settings: fakes, now=lambda: NOW).run(self.project)

    def test_detection_takes_the_first_strategy_that_finds_a_successful_deployment(self):
        settings = self.refresh(
            FakeSource(DeploymentStrategy.ENVIRONMENTS, [event(DeploymentStrategy.ENVIRONMENTS, "1", succeeded=False)]),
            FakeSource(DeploymentStrategy.RELEASE_TAGS, [event(DeploymentStrategy.RELEASE_TAGS, "v1")]),
            FakeSource(DeploymentStrategy.DEFAULT_BRANCH, [event(DeploymentStrategy.DEFAULT_BRANCH, "p1")]),
        )

        self.assertEqual(settings.strategy_in_use, DeploymentStrategy.RELEASE_TAGS)
        self.assertEqual(list(Deployment.objects.values_list("external_id", flat=True)), ["v1"])

    def test_detection_falls_back_to_the_default_branch_and_notes_what_it_could_not_read(self):
        settings = self.refresh(
            FakeSource(DeploymentStrategy.ENVIRONMENTS, unavailable="Give the token Deployments read access."),
            FakeSource(DeploymentStrategy.DEFAULT_BRANCH, [event(DeploymentStrategy.DEFAULT_BRANCH, "p1")]),
        )

        self.assertEqual(settings.strategy_in_use, DeploymentStrategy.DEFAULT_BRANCH)
        self.assertEqual(settings.refresh_error, "Give the token Deployments read access.")
        self.assertEqual(Deployment.objects.count(), 1)

    def test_a_chosen_strategy_is_used_even_when_it_finds_nothing(self):
        DeliverySettings.objects.create(project=self.project, strategy=DeploymentStrategy.DEPLOY_BRANCH)

        settings = self.refresh(
            FakeSource(DeploymentStrategy.ENVIRONMENTS, [event(DeploymentStrategy.ENVIRONMENTS, "1")]),
        )

        self.assertEqual(settings.strategy_in_use, DeploymentStrategy.DEPLOY_BRANCH)
        self.assertEqual(Deployment.objects.count(), 0)
        self.assertEqual(settings.refresh_error, "")

    def test_a_chosen_strategy_that_cannot_be_read_keeps_what_was_recorded(self):
        DeliverySettings.objects.create(project=self.project, strategy=DeploymentStrategy.DEPLOY_WORKFLOW)
        baker.make(Deployment, project=self.project, strategy=DeploymentStrategy.DEPLOY_WORKFLOW, deployed_at=NOW)

        settings = self.refresh(FakeSource(DeploymentStrategy.DEPLOY_WORKFLOW, unavailable="No workflow named deploy.yml."))

        self.assertEqual(settings.refresh_error, "No workflow named deploy.yml.")
        self.assertEqual(Deployment.objects.count(), 1)
        self.assertFalse(settings.refreshing)

    def test_finding_a_deployment_again_updates_it_in_place(self):
        DeliverySettings.objects.create(project=self.project, strategy=DeploymentStrategy.ENVIRONMENTS)
        running = FakeSource(DeploymentStrategy.ENVIRONMENTS, [event(DeploymentStrategy.ENVIRONMENTS, "7", succeeded=False)])
        self.refresh(running)
        running.events = [event(DeploymentStrategy.ENVIRONMENTS, "7", succeeded=True)]

        self.refresh(running)

        self.assertEqual(Deployment.objects.count(), 1)
        self.assertTrue(Deployment.objects.get().succeeded)

    def test_looks_back_a_week_past_the_frequency_window(self):
        source = FakeSource(DeploymentStrategy.DEFAULT_BRANCH)
        DeliverySettings.objects.create(project=self.project, strategy=DeploymentStrategy.DEFAULT_BRANCH)

        self.refresh(source)

        self.assertEqual(source.since, NOW - timedelta(weeks=14))


class DeliveryReportTests(TestCase):
    def setUp(self):
        self.project = baker.make(Project)

    def test_counts_only_the_strategy_in_use(self):
        DeliverySettings.objects.create(project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS)
        for days_ago in range(0, 91, 7):
            baker.make(
                Deployment, project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS,
                external_id=f"v{days_ago}", sha=f"s{days_ago}", deployed_at=NOW - timedelta(days=days_ago),
            )
        baker.make(Deployment, project=self.project, strategy=DeploymentStrategy.DEFAULT_BRANCH, deployed_at=NOW)

        report = DeliveryReport.for_project(self.project, now=NOW)

        self.assertEqual(report.frequency.total, 13)
        self.assertEqual(report.frequency.tier, DoraTier.HIGH)
        self.assertTrue(all(d.strategy == DeploymentStrategy.RELEASE_TAGS for d in report.recent))

    def test_before_any_refresh_there_is_nothing_to_rank(self):
        report = DeliveryReport.for_project(self.project, now=NOW)

        self.assertIsNone(report.strategy)
        self.assertEqual(report.frequency.tier, DoraTier.NONE)
        self.assertFalse(report.has_refreshed)


class DeploymentRefreshRequestTests(TestCase):
    def test_a_request_queues_a_refresh_and_marks_it_under_way(self):
        project = baker.make(Project)

        with mock.patch("app.tasks.refresh_deployments.configure") as configure:
            settings = DeploymentRefreshRequest.send(project)

        configure.assert_called_once_with(lock=f"deployments:{project.pk}", queueing_lock=f"deployments:{project.pk}")
        configure.return_value.defer.assert_called_once_with(project_id=str(project.pk))
        self.assertTrue(settings.refreshing)
