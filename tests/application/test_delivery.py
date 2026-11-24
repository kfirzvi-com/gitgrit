"""Delivery use cases: syncing a project's deployments (detection,
recording, problems), when syncs run, and the report the Delivery tab shows."""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app.application.delivery import (
    DeliveryReport,
    DeliverySync,
    DeliverySyncRequest,
    DeliverySyncSchedule,
    RateLimited,
    SourceUnavailable,
)
from app.domain.delivery import DeploymentEvent, DeploymentStrategy, DoraTier
from app.models import DeliverySettings, Deployment, Platform, Project

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
    def __init__(self, strategy, events=(), unavailable="", error=None):
        self.strategy = strategy
        self.events = list(events)
        self.unavailable = unavailable
        self.error = error
        self.since = None
        self.asked = False

    def find(self, since):
        self.since = since
        self.asked = True
        if self.error:
            raise self.error
        if self.unavailable:
            raise SourceUnavailable(self.unavailable)
        return self.events


class FakeSources:
    def __init__(self, *sources):
        self.by_strategy = {source.strategy: source for source in sources}

    def for_strategy(self, strategy):
        return self.by_strategy.get(strategy) or FakeSource(strategy)


class DeliverySyncTests(TestCase):
    def setUp(self):
        self.project = baker.make(Project)

    def refresh(self, *sources):
        fakes = FakeSources(*sources)
        return DeliverySync(lambda project, settings: fakes, now=lambda: NOW).run(self.project)

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

    def test_a_strategy_that_cannot_be_read_keeps_the_one_detected_before(self):
        DeliverySettings.objects.create(project=self.project, detected_strategy=DeploymentStrategy.RELEASE_TAGS)

        settings = self.refresh(FakeSource(DeploymentStrategy.ENVIRONMENTS, error=RateLimited(NOW)))

        self.assertEqual(settings.strategy_in_use, DeploymentStrategy.RELEASE_TAGS)

    def test_running_out_of_rate_limit_stops_detection_and_says_once_when_it_resumes(self):
        later = FakeSource(DeploymentStrategy.RELEASE_TAGS, [event(DeploymentStrategy.RELEASE_TAGS, "v1")])

        settings = self.refresh(FakeSource(DeploymentStrategy.ENVIRONMENTS, error=RateLimited(NOW)), later)

        self.assertFalse(later.asked)
        self.assertEqual(settings.refresh_error, str(RateLimited(NOW)))
        self.assertIn("resumes after 12:00 UTC", settings.refresh_error)

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


class DeliverySyncRequestTests(TestCase):
    def setUp(self):
        self.project = baker.make(Project)
        patcher = mock.patch("app.tasks.sync_delivery.configure")
        self.configure = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_request_queues_a_sync_and_marks_it_under_way(self):
        settings = DeliverySyncRequest.send(self.project)

        self.configure.assert_called_once_with(lock=f"delivery:{self.project.pk}", queueing_lock=f"delivery:{self.project.pk}")
        self.configure.return_value.defer.assert_called_once_with(project_id=str(self.project.pk))
        self.assertTrue(settings.refreshing)

    def test_refresh_by_hand_waits_out_the_cooldown_after_a_sync(self):
        DeliverySettings.objects.create(project=self.project, refreshed_at=NOW - timedelta(minutes=2))

        self.assertFalse(DeliverySyncRequest.refresh(self.project, now=NOW))
        self.assertTrue(DeliverySyncRequest.refresh(self.project, now=NOW + timedelta(minutes=4)))
        self.configure.assert_called_once()

    def test_refresh_by_hand_does_nothing_while_a_sync_is_under_way(self):
        DeliverySettings.objects.create(project=self.project, refresh_requested_at=NOW)

        self.assertFalse(DeliverySyncRequest.refresh(self.project, now=NOW + timedelta(hours=1)))
        self.configure.assert_not_called()


class DeliverySyncScheduleTests(TestCase):
    def due(self):
        return set(DeliverySyncSchedule.due(NOW))

    def project(self, **delivery):
        project = baker.make(Project, platform=Platform.GITHUB)
        if delivery:
            DeliverySettings.objects.create(project=project, **delivery)
        return project

    def test_projects_never_synced_are_due(self):
        fresh = self.project()
        opened = self.project(strategy=DeploymentStrategy.AUTO)

        self.assertEqual(self.due(), {fresh, opened})

    def test_a_project_is_due_once_its_interval_has_passed(self):
        stale = self.project(refreshed_at=NOW - timedelta(minutes=15))
        self.project(refreshed_at=NOW - timedelta(minutes=14))

        self.assertEqual(self.due(), {stale})

    def test_a_sync_under_way_is_left_alone_unless_it_was_asked_for_long_ago(self):
        self.project(refreshed_at=NOW - timedelta(hours=1), refresh_requested_at=NOW - timedelta(minutes=1))
        lost = self.project(refreshed_at=NOW - timedelta(hours=1), refresh_requested_at=NOW - timedelta(minutes=30))

        self.assertEqual(self.due(), {lost})

    def test_uploaded_builds_are_never_due(self):
        baker.make(Project, platform=Platform.ARTIFACT)

        self.assertEqual(self.due(), set())

    def test_the_interval_comes_from_the_setting(self):
        with self.settings(GITGRIT_DELIVERY_SYNC_MINUTES=60):
            self.assertEqual(DeliverySyncSchedule.policy().interval, timedelta(hours=1))


class DeliveryWebhookTests(TestCase):
    def setUp(self):
        self.project = baker.make(Project, default_branch="main")
        DeliverySettings.objects.create(project=self.project, deploy_branch="production")
        patcher = mock.patch("app.application.delivery.delivery_webhook.DeliverySyncRequest.send")
        self.send = patcher.start()
        self.addCleanup(patcher.stop)

    def receive(self, event_type, **fields):
        from app.application.delivery import DeliveryWebhook
        from app.domain.events import DomainEvent

        event = DomainEvent(event_type=event_type, platform="github", external_project_id="1", **fields)
        return DeliveryWebhook.receive(event, Project.objects.filter(pk=self.project.pk).select_related("delivery"))

    def test_a_release_or_deployment_status_asks_for_a_sync(self):
        self.assertEqual(self.receive("release"), 1)
        self.assertEqual(self.receive("deployment_status"), 1)

    def test_a_push_to_the_default_or_deploy_branch_asks_for_a_sync(self):
        self.assertEqual(self.receive("push", ref="refs/heads/main"), 1)
        self.assertEqual(self.receive("push", ref="refs/heads/production"), 1)

    def test_a_push_to_a_feature_branch_or_a_deleted_branch_does_not(self):
        self.assertEqual(self.receive("push", ref="refs/heads/feature/x"), 0)
        self.assertEqual(self.receive("push", ref="refs/heads/main", deleted=True), 0)
        self.send.assert_not_called()
