"""Metering a workspace's usage: executions and projects, per UTC day."""
from datetime import date
from importlib import import_module
from unittest import mock

from django.apps import apps
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application.standard_runs import enqueue_run
from app.application.usage import UsageMeter, UsageReport
from app.domain.models import StandardExecution, WorkspaceUsageDay
from app.domain.usage import BillingMonth
from tests.support import defer_patch

TODAY = date(2026, 11, 20)
NON_MANIFEST_STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


def _day(tenant, day=None):
    return WorkspaceUsageDay.objects.get(tenant=tenant, day=day or timezone.now().date())


class UsageMeterTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def test_executions_add_up_within_a_day(self):
        UsageMeter.record_executions(self.tenant.pk, 3, on=TODAY)
        UsageMeter.record_executions(self.tenant.pk, 2, on=TODAY)

        self.assertEqual(_day(self.tenant, TODAY).executions, 5)

    def test_each_day_has_its_own_row(self):
        UsageMeter.record_executions(self.tenant.pk, 3, on=date(2026, 11, 19))
        UsageMeter.record_executions(self.tenant.pk, 2, on=TODAY)

        self.assertEqual(WorkspaceUsageDay.objects.filter(tenant=self.tenant).count(), 2)

    def test_nothing_queued_records_nothing(self):
        UsageMeter.record_executions(self.tenant.pk, 0, on=TODAY)

        self.assertFalse(WorkspaceUsageDay.objects.exists())

    def test_running_notes_the_projects_held(self):
        baker.make("app.Project", tenant=self.tenant, _quantity=2)
        WorkspaceUsageDay.objects.all().delete()

        UsageMeter.record_executions(self.tenant.pk, 1, on=TODAY)

        self.assertEqual(_day(self.tenant, TODAY).peak_projects, 2)

    def test_the_project_peak_never_drops_within_a_day(self):
        projects = baker.make("app.Project", tenant=self.tenant, _quantity=3)
        UsageMeter.record_projects(self.tenant.pk, on=TODAY)
        projects[0].delete()

        UsageMeter.record_projects(self.tenant.pk, on=TODAY)

        self.assertEqual(_day(self.tenant, TODAY).peak_projects, 3)

    def test_a_metering_failure_never_fails_the_work(self):
        with mock.patch.object(WorkspaceUsageDay.objects, "get_or_create", side_effect=RuntimeError("db")):
            UsageMeter.record_executions(self.tenant.pk, 1, on=TODAY)  # no raise

    def test_snapshot_notes_every_workspace(self):
        other = baker.make("app.Tenant")
        baker.make("app.Project", tenant=other)

        UsageMeter.snapshot_all(on=TODAY)

        self.assertEqual((_day(self.tenant, TODAY).peak_projects, _day(other, TODAY).peak_projects), (0, 1))


class MeteringHooksTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def test_a_new_project_raises_the_days_peak(self):
        baker.make("app.Project", tenant=self.tenant, _quantity=2)

        self.assertEqual(_day(self.tenant).peak_projects, 2)

    def test_queued_runs_are_metered(self):
        project = baker.make("app.Project", tenant=self.tenant)
        standards = baker.make("app.Standard", tenant=self.tenant, _quantity=3)

        with defer_patch():
            enqueue_run(project, standards)

        self.assertEqual(_day(self.tenant).executions, 3)

    def test_runs_that_never_queue_are_not_metered(self):
        """The rows and the job roll back together, and so does the count."""
        project = baker.make("app.Project", tenant=self.tenant)
        standard = baker.make("app.Standard", tenant=self.tenant)

        with defer_patch(side_effect=RuntimeError("queue down")):
            with self.assertRaises(RuntimeError):
                enqueue_run(project, [standard])

        self.assertEqual(_day(self.tenant).executions, 0)

    def test_usage_outlives_a_deleted_project(self):
        project = baker.make("app.Project", tenant=self.tenant)
        with defer_patch():
            enqueue_run(project, [baker.make("app.Standard", tenant=self.tenant)])

        project.delete()

        self.assertEqual(_day(self.tenant).executions, 1)


class UsageReportTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def _usage(self, day, executions, projects=0):
        WorkspaceUsageDay.objects.create(tenant=self.tenant, day=day, executions=executions, peak_projects=projects)

    def test_the_current_month_and_the_ones_before(self):
        self._usage(date(2026, 11, 3), 40, 2)
        self._usage(date(2026, 11, 18), 60, 3)
        self._usage(date(2026, 10, 9), 25, 1)

        report = UsageReport.for_workspace(self.tenant, today=TODAY)

        self.assertEqual((report.current.month, report.current.executions), (BillingMonth(2026, 11), 100))
        self.assertEqual([str(m.month) for m in report.history],
                         ["2026-10", "2026-09", "2026-08", "2026-07", "2026-06"])
        self.assertEqual((report.history[0].executions, report.history[0].peak_projects), (25, 1))

    def test_other_workspaces_and_older_months_are_left_out(self):
        WorkspaceUsageDay.objects.create(tenant=baker.make("app.Tenant"), day=TODAY, executions=99)
        self._usage(date(2026, 1, 5), 7)

        report = UsageReport.for_workspace(self.tenant, today=TODAY)

        self.assertEqual(report.current.executions + sum(m.executions for m in report.history), 0)

    def test_the_peak_includes_the_projects_held_now(self):
        baker.make("app.Project", tenant=self.tenant, _quantity=2)  # metered today, not on TODAY
        report = UsageReport.for_workspace(self.tenant, today=TODAY)

        self.assertEqual((report.projects_now, report.peak_projects), (2, 2))


class BackfillUsageTests(TestCase):
    """0057 meters the history already stored: runs per UTC day, and the
    projects that existed by each such day."""

    def test_backfills_runs_per_workspace_and_day(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        for _ in range(3):
            baker.make("app.StandardExecution", project=project)
        WorkspaceUsageDay.objects.all().delete()

        import_module("app.migrations.0057_workspace_usage_days").backfill_usage_days(apps, None)

        row = WorkspaceUsageDay.objects.get(tenant=tenant)
        self.assertEqual((row.executions, row.peak_projects), (3, 1))
        self.assertEqual(StandardExecution.objects.count(), 3)


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class UsageSectionPageTests(TestCase):
    def test_workspace_settings_shows_the_usage(self):
        tenant = baker.make("app.Tenant")
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        baker.make("app.Project", tenant=tenant)
        UsageMeter.record_executions(tenant.pk, 1234)
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()

        body = self.client.get(reverse("tenant_settings")).content.decode()

        usage = body.split('id="section-usage"', 1)[1]
        self.assertIn("data-workspace-usage", usage)
        self.assertIn("1,234", usage)
