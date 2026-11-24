"""The dashboard's Delivery tab: the workspace's deploys and pull requests
summed over its synced projects, its deploy tiers and the latest
deployments."""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application.delivery import WorkspaceDelivery
from app.domain.delivery import DeploymentStrategy, DoraTier
from app.models import DeliverySettings, Deployment, Platform
from app.presentation.delivery_chart import DeliveryChart


class DashboardDeliveryTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        now = timezone.now()
        self.shop = baker.make("app.Project", tenant=self.tenant, name="shop", platform=Platform.GITHUB)
        self.api = baker.make("app.Project", tenant=self.tenant, name="api", platform=Platform.GITHUB)
        baker.make("app.Project", tenant=self.tenant, name="new", platform=Platform.GITHUB)
        baker.make("app.Project", tenant=self.tenant, name="build", platform=Platform.ARTIFACT)
        baker.make("app.Project", name="elsewhere", platform=Platform.GITHUB)
        for project, ref, hours in ((self.shop, "v1.0.0", 30), (self.api, "v2.0.0", 2)):
            DeliverySettings.objects.create(project=project, strategy=DeploymentStrategy.RELEASE_TAGS, refreshed_at=now)
            baker.make(Deployment, project=project, strategy=DeploymentStrategy.RELEASE_TAGS, ref=ref,
                       external_id=ref, deployed_at=now - timedelta(hours=hours))
        baker.make("app.PullRequest", project=self.shop, number=1, state="open", created_at=now, updated_at=now)

    def test_sums_the_workspaces_synced_git_projects_newest_deployment_first(self):
        delivery = WorkspaceDelivery.for_workspace(self.tenant)

        self.assertEqual((delivery.synced, delivery.projects), (2, 3))
        self.assertEqual(sum(delivery.totals.deployments), 2)
        self.assertEqual(delivery.totals.open_now, 1)
        self.assertEqual(dict(delivery.totals.tiers)[DoraTier.LOW], 2)
        self.assertEqual([project for project, _ in delivery.latest], [self.api, self.shop])

    def test_the_dashboard_has_a_delivery_tab(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'data-tab="tab-delivery"')
        self.assertContains(response, "Across 2 of 3 Git projects")
        self.assertContains(response, "v2.0.0")


class DeliveryChartTests(TestCase):
    def test_bars_fill_the_height_and_the_line_keeps_a_margin(self):
        starts = [date(2026, 11, 2), date(2026, 11, 9)]

        chart = DeliveryChart(starts, [2, 4], [1, 2])

        self.assertEqual([c.height for c in chart.columns], [50, 100])
        self.assertEqual([c.y for c in chart.columns], [54.0, 8.0])
        self.assertEqual(chart.points, "25.0,54.0 75.0,8.0")

    def test_an_empty_week_has_no_bar_and_sits_on_the_floor(self):
        chart = DeliveryChart([date(2026, 11, 2)], [0], [0])

        self.assertEqual((chart.columns[0].height, chart.columns[0].y), (0, 100.0))


class DashboardLeadTimeTests(TestCase):
    def test_the_workspace_median_pools_every_change_and_counts_projects_per_tier(self):
        from app.domain.delivery import DeliveryTotals, LeadTime, Shipment, ShippedCommit
        from datetime import datetime, timezone as tz

        noon = datetime(2026, 11, 16, 12, tzinfo=tz.utc)
        fast = LeadTime.of([Shipment("a", noon, (ShippedCommit("a", noon - timedelta(hours=2)),))], [], date(2026, 11, 16))
        slow = LeadTime.of([Shipment("b", noon, (ShippedCommit("b", noon - timedelta(days=10)), ShippedCommit("c", noon - timedelta(days=12))))], [], date(2026, 11, 16))

        totals = DeliveryTotals.of([], [], [fast, slow])

        self.assertEqual(totals.lead_time, timedelta(days=10))
        self.assertEqual(dict(totals.lead_tiers)[DoraTier.ELITE], 1)
        self.assertEqual(dict(totals.lead_tiers)[DoraTier.MEDIUM], 1)


class DeliverySpeedGaugeTests(DashboardDeliveryTests):
    def test_the_clusters_left_gauge_is_delivery_speed(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'data-gauge="speed"')
        self.assertContains(response, "DEPLOYS THIS WEEK")
        self.assertContains(response, "data-speed-readouts")
        self.assertNotContains(response, 'data-gauge="checks"')
