"""Metering a workspace's usage: executions and projects, per UTC day."""
from datetime import date
from importlib import import_module
from unittest import mock
from uuid import uuid4

from django.apps import apps
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.application.event_bus import publish
from app.application.standard_runs import enqueue_run
from app.domain.events import ProjectCreated
from app.application.usage import UsageMeter, UsageReport
from app.domain.models import ExecutionUsage, StandardExecution, WorkspaceUsageDay
from app.domain.usage import BillingMonth
from tests.support import defer_patch

TODAY = date(2026, 11, 20)
NON_MANIFEST_STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


def _day(tenant, day=None):
    return WorkspaceUsageDay.objects.get(tenant=tenant, day=day or timezone.now().date())


class UsageMeterTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="acme/api")

    def test_executions_add_up_within_a_day(self):
        UsageMeter.record_executions(self.project, 3, "push", on=TODAY)
        UsageMeter.record_executions(self.project, 2, "push", on=TODAY)

        self.assertEqual(_day(self.tenant, TODAY).executions, 5)

    def test_each_day_has_its_own_row(self):
        UsageMeter.record_executions(self.project, 3, "push", on=date(2026, 11, 19))
        UsageMeter.record_executions(self.project, 2, "push", on=TODAY)

        self.assertEqual(WorkspaceUsageDay.objects.filter(tenant=self.tenant).count(), 2)

    def test_nothing_queued_records_nothing(self):
        WorkspaceUsageDay.objects.all().delete()
        UsageMeter.record_executions(self.project, 0, "push", on=TODAY)

        self.assertFalse(WorkspaceUsageDay.objects.exists())

    def test_running_notes_the_projects_held(self):
        baker.make("app.Project", tenant=self.tenant)
        WorkspaceUsageDay.objects.all().delete()

        UsageMeter.record_executions(self.project, 1, "push", on=TODAY)

        self.assertEqual(_day(self.tenant, TODAY).peak_projects, 2)

    def test_the_project_peak_never_drops_within_a_day(self):
        projects = baker.make("app.Project", tenant=self.tenant, _quantity=2)
        UsageMeter.record_projects(self.tenant.pk, on=TODAY)
        projects[0].delete()

        UsageMeter.record_projects(self.tenant.pk, on=TODAY)

        self.assertEqual(_day(self.tenant, TODAY).peak_projects, 3)

    def test_a_metering_failure_never_fails_the_work(self):
        with mock.patch.object(WorkspaceUsageDay.objects, "get_or_create", side_effect=RuntimeError("db")):
            UsageMeter.record_executions(self.project, 1, "push", on=TODAY)  # no raise

    def test_snapshot_notes_every_workspace(self):
        other = baker.make("app.Tenant")
        baker.make("app.Project", tenant=other)

        UsageMeter.snapshot_all(on=TODAY)

        self.assertEqual((_day(self.tenant, TODAY).peak_projects, _day(other, TODAY).peak_projects), (1, 1))

    def test_executions_are_split_by_project_and_trigger(self):
        other = baker.make("app.Project", tenant=self.tenant, name="acme/web")
        UsageMeter.record_executions(self.project, 3, "push", on=TODAY)
        UsageMeter.record_executions(self.project, 2, "push", on=TODAY)
        UsageMeter.record_executions(self.project, 1, "manual", on=TODAY)
        UsageMeter.record_executions(other, 4, "pull_request", on=TODAY)

        split = sorted(ExecutionUsage.objects.values_list("project_name", "trigger", "executions"))

        self.assertEqual(split, [("acme/api", "manual", 1), ("acme/api", "push", 5), ("acme/web", "pull_request", 4)])
        self.assertEqual(_day(self.tenant, TODAY).executions, 10)

    def test_the_split_outlives_its_projects(self):
        """Deleted projects keep their own rows and their names."""
        other = baker.make("app.Project", tenant=self.tenant, name="acme/web")
        UsageMeter.record_executions(self.project, 1, "push", on=TODAY)
        UsageMeter.record_executions(other, 1, "push", on=TODAY)

        self.project.delete()
        other.delete()

        self.assertEqual(sorted(ExecutionUsage.objects.values_list("project_name", flat=True)), ["acme/api", "acme/web"])


class RunTimeTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="acme/api")

    def test_run_time_adds_up_per_day_project_and_trigger(self):
        UsageMeter.record_executions(self.project, 2, "push", on=TODAY)
        UsageMeter.record_run_time(self.project, "push", 40_000, on=TODAY)
        UsageMeter.record_run_time(self.project, "push", 20_000, on=TODAY)

        self.assertEqual(_day(self.tenant, TODAY).run_ms, 60_000)
        self.assertEqual(list(ExecutionUsage.objects.values_list("executions", "run_ms")), [(2, 60_000)])

    def test_the_sandbox_run_is_timed_and_metered(self):
        execution = self._execution()

        with mock.patch("app.application.standard_engine.time.monotonic", side_effect=[10.0, 12.5]):
            self._engine(return_value={"passed": True, "score": 100}).run_execution(execution, {})

        execution.refresh_from_db()
        self.assertEqual(execution.duration_ms, 2500)
        self.assertEqual(_day(self.tenant).run_ms, 2500)
        self.assertEqual(ExecutionUsage.objects.get().trigger, "pull_request")

    def test_a_run_that_crashes_still_spent_its_time(self):
        execution = self._execution()

        with mock.patch("app.application.standard_engine.time.monotonic", side_effect=[10.0, 11.0]):
            with self.assertRaises(RuntimeError):
                self._engine(side_effect=RuntimeError("sandbox died")).run_execution(execution, {})

        self.assertEqual(_day(self.tenant).run_ms, 1000)

    def test_a_run_that_never_reaches_the_sandbox_takes_no_time(self):
        """An artifact project with nothing uploaded fails before the sandbox."""
        project = baker.make("app.Project", tenant=self.tenant, platform="artifact")
        execution = self._execution(project=project)

        self._engine(return_value={"passed": True}).run_execution(execution, {})

        execution.refresh_from_db()
        self.assertIsNone(execution.duration_ms)
        self.assertEqual(WorkspaceUsageDay.objects.filter(tenant=self.tenant, run_ms__gt=0).count(), 0)

    def _execution(self, project=None):
        standard = baker.make("app.Standard", tenant=self.tenant, code="def check(ctx): pass")
        return baker.make("app.StandardExecution", project=project or self.project, standard=standard,
                          event_type="pull_request", status="running")

    def _engine(self, **run):
        from app.application.standard_engine import StandardEngine

        patch = mock.patch("app.application.standard_engine.SandboxRunner")
        runner = patch.start().return_value
        self.addCleanup(patch.stop)
        runner.run.configure_mock(**run)
        return StandardEngine()


class MeteringHooksTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def test_a_new_project_raises_the_days_peak(self):
        projects = baker.make("app.Project", tenant=self.tenant, _quantity=2)

        publish(ProjectCreated(project_id=str(projects[1].pk), tenant_id=str(self.tenant.pk)))

        self.assertEqual(_day(self.tenant).peak_projects, 2)

    def test_saving_a_project_alone_meters_nothing(self):
        """Usage follows domain events, not model saves."""
        baker.make("app.Project", tenant=self.tenant)

        self.assertFalse(WorkspaceUsageDay.objects.filter(tenant=self.tenant).exists())

    def test_a_new_artifact_project_is_metered(self):
        from app.application.artifact_service import create_artifact_project

        create_artifact_project(self.tenant, name="build", external_id="build-1")

        self.assertEqual(_day(self.tenant).peak_projects, 1)

    def test_queued_runs_are_metered(self):
        project = baker.make("app.Project", tenant=self.tenant)
        standards = baker.make("app.Standard", tenant=self.tenant, _quantity=3)

        with defer_patch():
            enqueue_run(project, standards)

        self.assertEqual(_day(self.tenant).executions, 3)
        self.assertEqual(list(ExecutionUsage.objects.values_list("trigger", "executions")), [("manual", 3)])

    def test_webhook_runs_are_metered_under_their_event(self):
        project = baker.make("app.Project", tenant=self.tenant)

        with defer_patch():
            enqueue_run(project, [baker.make("app.Standard", tenant=self.tenant)], event_type="pull_request")

        self.assertEqual(ExecutionUsage.objects.get().trigger, "pull_request")

    def test_runs_that_never_queue_are_not_metered(self):
        """The rows and the job roll back together, and so does the count."""
        project = baker.make("app.Project", tenant=self.tenant)
        standard = baker.make("app.Standard", tenant=self.tenant)

        with defer_patch(side_effect=RuntimeError("queue down")):
            with self.assertRaises(RuntimeError):
                enqueue_run(project, [standard])

        self.assertFalse(WorkspaceUsageDay.objects.filter(tenant=self.tenant, executions__gt=0).exists())
        self.assertFalse(ExecutionUsage.objects.exists())

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

        self.assertEqual((report.shown.month, report.shown.executions), (BillingMonth(2026, 11), 100))
        self.assertEqual([str(m.month) for m in report.months],
                         ["2026-11", "2026-10", "2026-09", "2026-08", "2026-07", "2026-06"])
        self.assertEqual((report.months[1].executions, report.months[1].peak_projects), (25, 1))

    def test_other_workspaces_and_older_months_are_left_out(self):
        WorkspaceUsageDay.objects.create(tenant=baker.make("app.Tenant"), day=TODAY, executions=99)
        self._usage(date(2026, 1, 5), 7)

        report = UsageReport.for_workspace(self.tenant, today=TODAY)

        self.assertEqual(sum(m.executions for m in report.months), 0)

    def test_the_peak_includes_the_projects_held_now(self):
        baker.make("app.Project", tenant=self.tenant, _quantity=2)  # metered today, not on TODAY
        report = UsageReport.for_workspace(self.tenant, today=TODAY)

        self.assertEqual((report.projects_now, report.peak_projects), (2, 2))

    def test_a_past_month_can_be_shown_with_its_split(self):
        self._usage(date(2026, 10, 9), 25, 1)
        ExecutionUsage.objects.create(tenant=self.tenant, day=date(2026, 10, 9), project_id=uuid4(),
                                      project_name="acme/api", trigger="push", executions=25)

        report = UsageReport.for_workspace(self.tenant, month=BillingMonth(2026, 10), today=TODAY)

        self.assertFalse(report.is_current)
        self.assertEqual([(s.name, s.executions) for s in report.shown.breakdown.by_project()], [("acme/api", 25)])
        self.assertEqual((report.newer, report.older), (BillingMonth(2026, 11), BillingMonth(2026, 9)))

    def test_a_month_out_of_reach_shows_the_current_one(self):
        report = UsageReport.for_workspace(self.tenant, month=BillingMonth(2025, 1), today=TODAY)

        self.assertTrue(report.is_current)
        self.assertIsNone(report.newer)


class BackfillUsageTests(TestCase):
    """0057 meters the history already stored: runs per UTC day, and the
    projects that existed by each such day."""

    def test_backfills_runs_per_workspace_and_day(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant, name="acme/api")
        for event in ("push", "push", "manual"):
            baker.make("app.StandardExecution", project=project, event_type=event)
        WorkspaceUsageDay.objects.all().delete()

        import_module("app.migrations.0057_workspace_usage").backfill_usage(apps, None)

        row = WorkspaceUsageDay.objects.get(tenant=tenant)
        self.assertEqual((row.executions, row.peak_projects), (3, 1))
        self.assertEqual(sorted(ExecutionUsage.objects.values_list("trigger", "executions")),
                         [("manual", 1), ("push", 2)])


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class UsageSectionPageTests(TestCase):
    def test_workspace_settings_shows_the_usage(self):
        tenant = baker.make("app.Tenant")
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        project = baker.make("app.Project", tenant=tenant, name="acme/api")
        UsageMeter.record_executions(project, 1234, "push")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()

        body = self.client.get(reverse("tenant_settings")).content.decode()

        usage = body.split('id="section-usage"', 1)[1]
        self.assertIn("data-workspace-usage", usage)
        self.assertIn("1,234", usage)
        self.assertIn('id="workspace-usage-data"', usage)  # what the hover and details read
        self.assertIn("acme/api", usage)

    def test_another_month_swaps_in_place(self):
        tenant = baker.make("app.Tenant")
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        last = BillingMonth.of(timezone.now().date()).previous()

        body = self.client.get(reverse("workspace_usage"), {"month": str(last)}).content.decode()

        self.assertIn(f'data-month="{last}"', body)
        self.assertNotIn("<html", body)


class MinutesTextTests(TestCase):
    def test_reads_run_time_the_way_people_do(self):
        from app.presentation.usage_section import minutes_text

        self.assertEqual([minutes_text(m) for m in (0, 0.5, 2.25, 1234.4)], ["0 min", "30s", "2.2 min", "1,234 min"])


class UsageMetricsTests(TestCase):
    """Executions and run time each get their own card, every figure named."""

    def test_each_meter_has_its_own_labeled_figures(self):
        from app.presentation.usage_section import UsageSection

        tenant = baker.make("app.Tenant")
        WorkspaceUsageDay.objects.create(tenant=tenant, day=date(2026, 11, 2), executions=40, run_ms=1_200_000)

        executions, run_time = UsageSection(UsageReport.for_workspace(tenant, today=TODAY)).metrics

        self.assertEqual((executions.label, executions.total), ("Executions", "40"))
        self.assertEqual((run_time.label, run_time.total), ("Run time", "20.0 min"))
        self.assertIn(("Busiest day", "40 on Nov 2"), executions.figures)
        self.assertIn(("Per run (avg)", "30s"), run_time.figures)
        self.assertIn(("Per day (avg)", "1.0 min"), run_time.figures)  # 20 min over 20 days
