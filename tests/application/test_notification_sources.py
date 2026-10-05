"""The "could not evaluate" translator: run finished -> run.failed notice."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import event_bus, subscribers
from app.application.notifications import sources
from app.domain.events import DependencyInferenceFailed, StandardRunFinished
from app.domain.models import Notification, StandardExecution
from tests.support import notify_defer_patch


class NotificationSourcesTests(TestCase):
    def setUp(self):
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        patch = notify_defer_patch()
        patch.start()
        self.addCleanup(patch.stop)
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="Acme")

    def _row(self, status=StandardExecution.Status.ERROR, **kwargs):
        standard = baker.make("app.Standard", tenant=self.tenant)
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            event_type="manual",
            status=status,
            **kwargs,
        )

    def _event(self, rows, passed=0, failed=0, errored=None, error=""):
        return StandardRunFinished(
            project_id=str(self.project.pk),
            tenant_id=str(self.tenant.pk),
            execution_ids=tuple(str(r.pk) for r in rows),
            passed=passed,
            failed=failed,
            errored=len(rows) if errored is None else errored,
            error=error,
        )

    def test_job_level_error(self):
        row = self._row()
        sources.on_standard_run_finished(
            self._event([row], error="401 Bad credentials\ntraceback...")
        )
        n = Notification.objects.get()
        self.assertEqual(n.kind, "run.failed")
        self.assertEqual(n.severity, "critical")
        self.assertIn("Acme", n.title)
        self.assertEqual(n.body, "401 Bad credentials")
        self.assertEqual(n.url, reverse("standard_execution_detail", args=[row.pk]))
        self.assertEqual(n.dedupe_key, f"run_failed:{self.project.pk}")
        self.assertEqual(n.context["project_id"], str(self.project.pk))
        self.assertEqual(n.context["execution_ids"], [str(row.pk)])

    def test_all_rows_errored_uses_row_error(self):
        row = self._row(details={"error": "sandbox exploded"})
        sources.on_standard_run_finished(self._event([row]))
        self.assertEqual(Notification.objects.get().body, "sandbox exploded")

    def test_mixed_run_is_not_run_failed(self):
        rows = [self._row(), self._row(status=StandardExecution.Status.PASSED)]
        sources.on_standard_run_finished(
            self._event(rows, passed=1, failed=1, errored=1)
        )
        self.assertFalse(Notification.objects.filter(kind="run.failed").exists())

    def test_clean_run_is_ignored(self):
        row = self._row(status=StandardExecution.Status.PASSED)
        sources.on_standard_run_finished(
            self._event([row], passed=1, failed=0, errored=0)
        )
        self.assertEqual(Notification.objects.count(), 0)

    def test_triggering_user_is_mentioned(self):
        user = baker.make("app.User")
        row = self._row(triggered_by_user=user)
        sources.on_standard_run_finished(self._event([row], error="boom"))
        self.assertEqual(
            Notification.objects.get().context["mentioned_user_ids"], [str(user.pk)]
        )

    def test_same_event_twice_does_not_raise(self):
        event = self._event([self._row()], error="boom")
        sources.on_standard_run_finished(event)
        sources.on_standard_run_finished(event)
        self.assertEqual(Notification.objects.count(), 2)

    def test_register_subscribes_handler(self):
        event_bus.clear()
        subscribers.register()
        event_bus.publish(self._event([self._row()], error="boom"))
        self.assertEqual(Notification.objects.filter(kind="run.failed").count(), 1)


class StandardsFailingTests(TestCase):
    def setUp(self):
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        patch = notify_defer_patch()
        patch.start()
        self.addCleanup(patch.stop)
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="Acme")

    def _row(self, status, score, name=None, attach=True, **kwargs):
        standard = baker.make("app.Standard", tenant=self.tenant)
        if attach:
            self.project.standards.add(standard)
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=name or standard.name,
            event_type="manual",
            status=status,
            score=score,
            **kwargs,
        )

    def _failed(self, score, name=None, **kwargs):
        return self._row(StandardExecution.Status.FAILED, score, name, **kwargs)

    def _event(self, rows, passed=0, failed=0, errored=0, error=""):
        return StandardRunFinished(
            project_id=str(self.project.pk),
            tenant_id=str(self.tenant.pk),
            execution_ids=tuple(str(r.pk) for r in rows),
            passed=passed,
            failed=failed,
            errored=errored,
            error=error,
        )

    def _two_failed_one_passed(self, **kwargs):
        rows = [
            self._failed(80, "Pinned CI", **kwargs),
            self._failed(20, "README present", **kwargs),
            self._row(StandardExecution.Status.PASSED, 100, **kwargs),
        ]
        return rows

    def test_failed_run_notifies_once(self):
        rows = self._two_failed_one_passed()
        sources.on_standard_run_finished(self._event(rows, passed=1, failed=2))
        n = Notification.objects.get()
        self.assertEqual(n.kind, "standards.failing")
        self.assertEqual(n.severity, "warning")
        self.assertEqual(n.title, "2 standards failing on Acme")
        self.assertIn("score 67/100: README present, Pinned CI", n.body)
        self.assertTrue(n.url.endswith("#project-results"))
        self.assertEqual(
            n.url, reverse("project_detail", args=[self.project.pk]) + "#project-results"
        )
        self.assertEqual(n.dedupe_key, f"standards:{self.project.pk}")
        self.assertEqual(n.context["project_id"], str(self.project.pk))
        self.assertEqual(len(n.context["failed_standard_ids"]), 2)

    def test_singular_title(self):
        rows = [
            self._failed(10),
            self._row(StandardExecution.Status.PASSED, 100),
        ]
        sources.on_standard_run_finished(self._event(rows, passed=1, failed=1))
        self.assertEqual(
            Notification.objects.get().title, "1 standard failing on Acme"
        )

    def test_more_than_three_names_are_capped(self):
        rows = [self._failed(i * 10, f"Std {i}") for i in range(5)]
        sources.on_standard_run_finished(self._event(rows, failed=5))
        body = Notification.objects.get().body
        self.assertIn("Std 0, Std 1, Std 2 and 2 more", body)
        self.assertNotIn("Std 3", body)

    def test_clean_run_is_ignored(self):
        rows = [self._row(StandardExecution.Status.PASSED, 100)]
        sources.on_standard_run_finished(self._event(rows, passed=1))
        self.assertEqual(Notification.objects.count(), 0)

    def test_job_error_only_notifies_run_failed(self):
        rows = self._two_failed_one_passed()
        sources.on_standard_run_finished(
            self._event(rows, passed=1, failed=2, error="boom")
        )
        self.assertEqual(
            list(Notification.objects.values_list("kind", flat=True)), ["run.failed"]
        )

    def test_superseded_failure_sends_nothing(self):
        # Standard not attached to the project: the current picture shows
        # nothing failing, so a "0 standards failing" item would be noise.
        rows = [self._failed(0, "README present", attach=False)]
        sources.on_standard_run_finished(self._event(rows, failed=1))
        self.assertFalse(Notification.objects.exists())

    def test_triggering_user_is_mentioned(self):
        user = baker.make("app.User")
        rows = [self._failed(10, triggered_by_user=user)]
        sources.on_standard_run_finished(self._event(rows, failed=1))
        self.assertEqual(
            Notification.objects.get().context["mentioned_user_ids"], [str(user.pk)]
        )


class DependencyGraphFailedTests(TestCase):
    def setUp(self):
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        patch = notify_defer_patch()
        patch.start()
        self.addCleanup(patch.stop)
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="Acme")

    def _event(self, had_worked_before=True, tenant_id=None):
        return DependencyInferenceFailed(
            project_id=str(self.project.pk),
            tenant_id=tenant_id or str(self.tenant.pk),
            error="LLM timed out\ntraceback...",
            had_worked_before=had_worked_before,
        )

    def test_had_worked_before_notifies(self):
        sources.on_dependency_inference_failed(self._event())
        n = Notification.objects.get()
        self.assertEqual(n.kind, "graph.failed")
        self.assertEqual(n.severity, "warning")
        self.assertIn("Acme", n.title)
        self.assertEqual(n.body, "LLM timed out")
        self.assertTrue(n.url.endswith("#components"))
        self.assertEqual(n.dedupe_key, f"graph:{self.project.pk}")

    def test_never_worked_is_quiet(self):
        sources.on_dependency_inference_failed(self._event(had_worked_before=False))
        self.assertFalse(Notification.objects.exists())

    def test_other_tenant_is_quiet(self):
        other = baker.make("app.Tenant")
        sources.on_dependency_inference_failed(self._event(tenant_id=str(other.pk)))
        self.assertFalse(Notification.objects.exists())

    def test_published_event_creates_row(self):
        event_bus.clear()
        subscribers.register()
        event_bus.publish(self._event())
        self.assertEqual(Notification.objects.filter(kind="graph.failed").count(), 1)
