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
from app.domain.delivery import DeploymentEvent, DeploymentStrategy, DoraTier, PendingCommits, PullRequestFacts
from app.models import DeliverySettings, Deployment, Platform, Project, PullRequest

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


class FakeActivity:
    def __init__(self, pending=None, unavailable=""):
        self.pending = pending
        self.unavailable = unavailable
        self.compared = None
        self.open = []
        self.updated = []
        self.asked_since = []
        self.shipped = {}

    def open_pull_requests(self):
        return self.open

    def commits_between(self, base_sha, head_sha):
        return self.shipped.get((base_sha, head_sha))

    def pull_requests_updated_since(self, since):
        self.asked_since.append(since)
        return self.updated

    def pending_commits(self, deployed_sha, branch):
        self.compared = (deployed_sha, branch)
        if self.unavailable:
            raise SourceUnavailable(self.unavailable)
        return self.pending


def pull(number, opened_days_ago=3, merged_days_ago=None, updated_days_ago=None):
    return PullRequestFacts(
        number=number, title=f"Change {number}", author="dev", url=f"https://example.test/pull/{number}",
        created_at=NOW - timedelta(days=opened_days_ago),
        updated_at=NOW - timedelta(days=updated_days_ago if updated_days_ago is not None else (merged_days_ago or opened_days_ago)),
        merged_at=NOW - timedelta(days=merged_days_ago) if merged_days_ago is not None else None,
        closed_at=NOW - timedelta(days=merged_days_ago) if merged_days_ago is not None else None,
    )


class DeliverySyncTests(TestCase):
    def setUp(self):
        self.project = baker.make(Project, default_branch="main")
        self.activity = FakeActivity()

    def refresh(self, *sources):
        fakes = FakeSources(*sources)
        return DeliverySync(lambda project, settings: fakes, lambda project: self.activity, now=lambda: NOW).run(
            self.project
        )

    def test_counts_the_commits_waiting_behind_the_running_version(self):
        self.activity.pending = PendingCommits(4, NOW - timedelta(days=2))

        settings = self.refresh(
            FakeSource(DeploymentStrategy.RELEASE_TAGS, [
                event(DeploymentStrategy.RELEASE_TAGS, "v1", days_ago=5),
                event(DeploymentStrategy.RELEASE_TAGS, "v2", days_ago=1),
            ]),
        )

        self.assertEqual(self.activity.compared, ("sha-v2", "main"))
        self.assertEqual(settings.pending, PendingCommits(4, NOW - timedelta(days=2)))

    def test_nothing_waits_to_ship_before_anything_runs(self):
        DeliverySettings.objects.create(project=self.project, pending_commits=3, oldest_pending_at=NOW)

        settings = self.refresh()

        self.assertIsNone(self.activity.compared)
        self.assertIsNone(settings.pending)

    def test_commits_that_cannot_be_compared_keep_the_last_count_and_say_why(self):
        DeliverySettings.objects.create(project=self.project, pending_commits=3, oldest_pending_at=NOW)
        self.activity.unavailable = "The GitHub token can't read contents."

        settings = self.refresh(FakeSource(DeploymentStrategy.RELEASE_TAGS, [event(DeploymentStrategy.RELEASE_TAGS, "v1")]))

        self.assertEqual(settings.pending_commits, 3)
        self.assertIn("can't read contents", settings.refresh_error)

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

    def test_the_first_sync_reads_every_open_pull_request_and_the_windows_changes(self):
        self.activity.open = [pull(1, opened_days_ago=400)]
        self.activity.updated = [pull(2, merged_days_ago=5), pull(1, opened_days_ago=400, updated_days_ago=1)]

        self.refresh()

        self.assertEqual(self.activity.asked_since, [NOW - timedelta(weeks=14)])
        self.assertEqual(sorted(PullRequest.objects.values_list("number", "state")), [(1, "open"), (2, "merged")])

    def test_later_syncs_read_only_what_changed_since_the_newest_stored_change(self):
        self.activity.updated = [pull(1, updated_days_ago=2)]
        self.refresh()
        self.activity.asked_since.clear()
        self.activity.updated = [pull(1, merged_days_ago=0)]

        self.refresh()

        self.assertEqual(self.activity.asked_since, [NOW - timedelta(days=2) - timedelta(minutes=5)])
        self.assertEqual(PullRequest.objects.get(number=1).state, "merged")

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

    def test_reports_the_running_version_and_what_waits_behind_it(self):
        DeliverySettings.objects.create(
            project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS, pending_commits=2, oldest_pending_at=NOW
        )
        baker.make(Deployment, project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS, ref="v3.1.0",
                   external_id="v3.1.0", deployed_at=NOW - timedelta(days=1))

        report = DeliveryReport.for_project(self.project, now=NOW)

        self.assertEqual(report.running.label, "v3.1.0")
        self.assertEqual(report.pending.count, 2)

    def test_reports_pull_request_flow_and_lists_open_ones_oldest_first(self):
        from app.application.delivery import PullRequestRefresh

        PullRequestRefresh.record(self.project, [
            pull(1, opened_days_ago=2), pull(2, opened_days_ago=30), pull(3, merged_days_ago=1),
            pull(4, opened_days_ago=200, merged_days_ago=150),
        ])

        report = DeliveryReport.for_project(self.project, now=NOW)

        self.assertEqual(report.pull_requests.open_now, 2)
        self.assertEqual(report.pull_requests.merged, 1)
        self.assertEqual([pr.number for pr in report.open_pull_requests], [2, 1])

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

    def test_a_pull_request_event_is_recorded_from_its_payload(self):
        from app.application.delivery import DeliveryWebhook
        from app.domain.events import DomainEvent

        event = DomainEvent(event_type="pull_request", platform="github", external_project_id="1", raw_payload={"n": 7})
        projects = Project.objects.filter(pk=self.project.pk).select_related("delivery")

        DeliveryWebhook.receive(event, projects, read_pull_request=lambda payload: pull(payload["n"]))

        self.assertEqual(PullRequest.objects.get(project=self.project).number, 7)
        self.send.assert_not_called()

    def test_a_push_to_a_feature_branch_or_a_deleted_branch_does_not(self):
        self.assertEqual(self.receive("push", ref="refs/heads/feature/x"), 0)
        self.assertEqual(self.receive("push", ref="refs/heads/main", deleted=True), 0)
        self.send.assert_not_called()


class ShipmentRefreshTests(TestCase):
    def setUp(self):
        self.project = baker.make(Project, default_branch="main")
        self.settings = DeliverySettings.objects.create(project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS)
        self.activity = FakeActivity()

    def deploy(self, tag, days_ago, sha=None, succeeded=True):
        return baker.make(Deployment, project=self.project, strategy=DeploymentStrategy.RELEASE_TAGS, external_id=tag,
                          sha=sha or f"sha-{tag}", deployed_at=NOW - timedelta(days=days_ago), succeeded=succeeded)

    def run_refresh(self):
        from app.application.delivery import ShipmentRefresh

        return ShipmentRefresh(now=lambda: NOW).run(self.project, self.settings, self.activity)

    def test_each_deployment_ships_what_its_commit_has_beyond_the_previous_ones(self):
        from app.domain.delivery import ShippedCommit as Commit

        self.deploy("v1", 10)
        self.deploy("v2-broken", 6, succeeded=False)
        v2 = self.deploy("v2", 5)
        self.activity.shipped[("sha-v1", "sha-v2")] = [Commit("c1", NOW - timedelta(days=7), "sha-v1"), Commit("sha-v2", NOW - timedelta(days=6), "c1")]

        self.assertEqual(self.run_refresh(), 2)

        self.assertEqual(sorted(v2.shipped_commits.values_list("sha", flat=True)), ["c1", "sha-v2"])
        self.assertEqual(self.run_refresh(), 0)  # each deployment is read once

    def test_a_redeploy_of_the_same_commit_ships_nothing_new(self):
        self.deploy("eu", 3, sha="abc")
        us = self.deploy("us", 2, sha="abc")
        self.activity.shipped[("abc", "abc")] = "should not be asked"

        self.run_refresh()

        self.assertFalse(us.shipped_commits.exists())


class LeadTimesTests(TestCase):
    def test_a_projects_lead_time_from_its_chosen_start(self):
        from app.application.delivery import LeadTimes, PullRequestRefresh
        from app.models import ShippedCommit as StoredCommit

        project = baker.make(Project)
        settings = DeliverySettings.objects.create(project=project, strategy=DeploymentStrategy.RELEASE_TAGS, lead_time_start="merge")
        deployment = baker.make(Deployment, project=project, strategy=DeploymentStrategy.RELEASE_TAGS, sha="m",
                                deployed_at=NOW - timedelta(hours=1), succeeded=True)
        StoredCommit.objects.create(deployment=deployment, sha="m", authored_at=NOW - timedelta(days=3), first_parent_sha="p")
        PullRequestRefresh.record(project, [PullRequestFacts(
            number=4, title="", author="", url="", created_at=NOW - timedelta(days=3), updated_at=NOW,
            merged_at=NOW - timedelta(hours=5), closed_at=NOW - timedelta(hours=5), merge_commit_sha="m",
        )])

        lead = LeadTimes.for_project(settings, NOW)

        self.assertEqual(lead.median, timedelta(hours=4))
        self.assertEqual(lead.changes[0].pull_request, 4)
