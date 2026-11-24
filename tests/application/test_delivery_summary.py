"""Delivery summaries for pages that list many projects: each project's
running version, deploy frequency and pull request flow, read in a few
queries."""
from datetime import datetime, timedelta, timezone

from django.test import TestCase
from model_bakery import baker

from app.application.delivery import DeliverySummary, PullRequestRefresh
from app.domain.delivery import DeploymentStrategy, DoraTier, PullRequestFacts
from app.models import DeliverySettings, Deployment, Project

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


class DeliverySummaryTests(TestCase):
    def setUp(self):
        self.weekly = baker.make(Project)
        self.quiet = baker.make(Project)
        self.unsynced = baker.make(Project)
        DeliverySettings.objects.create(project=self.weekly, strategy=DeploymentStrategy.RELEASE_TAGS, refreshed_at=NOW)
        DeliverySettings.objects.create(project=self.quiet, detected_strategy=DeploymentStrategy.DEFAULT_BRANCH, refreshed_at=NOW)
        for week in range(13):
            baker.make(Deployment, project=self.weekly, strategy=DeploymentStrategy.RELEASE_TAGS, sha=f"s{week}",
                       external_id=f"v1.{week}", ref=f"v1.{week}", deployed_at=NOW - timedelta(weeks=week))
        # Counted by another strategy than the one in use: left out.
        baker.make(Deployment, project=self.weekly, strategy=DeploymentStrategy.DEFAULT_BRANCH, deployed_at=NOW)
        PullRequestRefresh.record(self.quiet, [PullRequestFacts(
            number=1, title="Fix", author="dev", url="", created_at=NOW - timedelta(days=2), updated_at=NOW,
        )])

    def summaries(self):
        return DeliverySummary.for_projects([self.weekly, self.quiet, self.unsynced], now=NOW)

    def test_each_project_gets_its_running_version_tier_and_open_pull_requests(self):
        summaries = self.summaries()

        self.assertEqual(summaries[self.weekly.pk].running.label, "v1.0")
        self.assertEqual(summaries[self.weekly.pk].frequency.tier, DoraTier.HIGH)
        self.assertEqual(summaries[self.weekly.pk].frequency.total, 13)
        self.assertIsNone(summaries[self.quiet.pk].running)
        self.assertEqual(summaries[self.quiet.pk].pull_requests.open_now, 1)

    def test_a_project_never_synced_says_so(self):
        summaries = self.summaries()

        self.assertFalse(summaries[self.unsynced.pk].synced)
        self.assertTrue(summaries[self.quiet.pk].synced)

    def test_reads_in_a_fixed_number_of_queries(self):
        with self.assertNumQueries(3):
            self.summaries()
