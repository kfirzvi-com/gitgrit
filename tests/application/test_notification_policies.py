"""Policies: a finished run or a broken map becomes the right notification."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import event_bus, subscribers
from app.application.notifications.policies import (
    CouldNotEvaluatePolicy,
    GraphBrokePolicy,
    StandardsFailingPolicy,
)
from app.domain.events import DependencyInferenceFailed, StandardRunFinished
from app.domain.models import Notification, StandardExecution
from tests.support import deliver_defer_patch


class _PolicyTestCase(TestCase):
    def setUp(self):
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        patch = deliver_defer_patch()
        self.defer = patch.start()
        self.addCleanup(patch.stop)
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="Acme")

    def _row(self, status, score=0, name=None, attach=True, **kwargs):
        standard = baker.make("app.Standard", tenant=self.tenant)
        if attach:
            self.project.standards.add(standard)
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=name or standard.name,
            status=status,
            score=score,
            **{"event_type": "manual", **kwargs},
        )

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


class CouldNotEvaluatePolicyTests(_PolicyTestCase):
    policy = CouldNotEvaluatePolicy()

    def _errored(self, **kwargs):
        return self._row(StandardExecution.Status.ERROR, **kwargs)

    def test_job_level_error_raises_it_and_queues_delivery(self):
        row = self._errored()
        self.policy.handle(self._event([row], errored=1, error="401 Bad credentials\ntraceback..."))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "run.failed")
        self.assertEqual(n.body, "401 Bad credentials")
        self.assertEqual(n.url, reverse("standard_execution_detail", args=[row.pk]))
        self.assertEqual(n.context["project_name"], "Acme")
        self.assertEqual(n.context["execution_ids"], [str(row.pk)])
        self.assertEqual(n.context["trigger"], "manual")
        self.defer.assert_called_once_with(notification_id=str(n.pk))

    def test_all_rows_errored_uses_the_row_error(self):
        row = self._errored(details={"error": "sandbox exploded"})
        self.policy.handle(self._event([row], errored=1))
        self.assertEqual(Notification.objects.get().body, "sandbox exploded")

    def test_sandbox_error_flag_falls_back_to_the_exception_line(self):
        """The sandbox marks a raising standard with ``details={"error": True}``
        and puts the traceback in ``message``."""
        row = self._errored(
            details={"error": True},
            message=(
                "Standard execution error: Traceback (most recent call last):\n"
                '  File "/entrypoint.py", line 1, in <module>\n'
                "RuntimeError: boom from standard"
            ),
        )
        self.policy.handle(self._event([row], errored=1))
        self.assertEqual(Notification.objects.get().body, "RuntimeError: boom from standard")

    def test_a_mixed_run_is_not_its_business(self):
        rows = [self._errored(), self._row(StandardExecution.Status.PASSED, 100)]
        self.policy.handle(self._event(rows, passed=1, failed=1, errored=1))
        self.assertFalse(Notification.objects.exists())

    def test_the_triggering_user_is_recorded_for_routing(self):
        user = baker.make("app.User")
        row = self._errored(triggered_by_user=user)
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertEqual(Notification.objects.get().triggered_by_user_ids, [str(user.pk)])

    def test_trigger_prefers_the_webhook_event_over_the_actor(self):
        row = self._errored(event_type="push", triggered_by="octocat")
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertEqual(Notification.objects.get().context["trigger"], "push")

    def test_trigger_uses_the_app_reason_for_manual_runs(self):
        row = self._errored(event_type="manual", triggered_by="attached")
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertEqual(Notification.objects.get().context["trigger"], "attached")

    def test_trigger_falls_back_to_the_event_type(self):
        row = self._errored(event_type="schedule", triggered_by="someone")
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertEqual(Notification.objects.get().context["trigger"], "schedule")

    def test_trigger_is_omitted_when_unknown(self):
        row = self._errored(event_type="", triggered_by="")
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertNotIn("trigger", Notification.objects.get().context)

    def test_the_same_event_twice_raises_two(self):
        event = self._event([self._errored()], errored=1, error="boom")
        self.policy.handle(event)
        self.policy.handle(event)
        self.assertEqual(Notification.objects.count(), 2)

    def test_another_workspaces_project_is_ignored(self):
        event = StandardRunFinished(
            project_id=str(self.project.pk), tenant_id=str(baker.make("app.Tenant").pk),
            execution_ids=(), passed=0, failed=0, errored=1, error="boom",
        )
        self.policy.handle(event)
        self.assertFalse(Notification.objects.exists())


class StandardsFailingPolicyTests(_PolicyTestCase):
    policy = StandardsFailingPolicy()

    def _failed(self, score, name=None, **kwargs):
        return self._row(StandardExecution.Status.FAILED, score, name, **kwargs)

    def test_a_failing_run_raises_one_for_the_run(self):
        rows = [
            self._failed(80, "Pinned CI"),
            self._failed(20, "README present"),
            self._row(StandardExecution.Status.PASSED, 100),
        ]
        self.policy.handle(self._event(rows, passed=1, failed=2))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "standards.failing")
        self.assertEqual(n.title, "2 standards failed")
        self.assertEqual(n.body, "README present, Pinned CI")  # worst first
        self.assertEqual(n.context["score"], 67)
        self.assertEqual(len(n.context["failed_standard_ids"]), 2)
        self.assertEqual(n.context["trigger"], "manual")

    def test_the_count_is_this_runs_failures_not_the_projects(self):
        self._failed(0, "Older failure")
        rows = [self._failed(40, "Pinned CI")]
        self.policy.handle(self._event(rows, failed=1))

        n = Notification.objects.get()
        self.assertEqual(n.title, "1 standard failed")
        self.assertEqual(n.body, "Pinned CI")
        self.assertEqual(n.context["score"], 20)

    def test_trigger_comes_from_this_runs_rows(self):
        rows = [self._failed(10, event_type="pull_request", triggered_by="octocat")]
        self.policy.handle(self._event(rows, failed=1))
        self.assertEqual(Notification.objects.get().context["trigger"], "pull_request")

    def test_a_clean_run_raises_nothing(self):
        rows = [self._row(StandardExecution.Status.PASSED, 100)]
        self.policy.handle(self._event(rows, passed=1))
        self.assertFalse(Notification.objects.exists())

    def test_a_run_that_could_not_be_evaluated_is_left_to_the_other_policy(self):
        rows = [self._failed(10)]
        self.policy.handle(self._event(rows, failed=1, error="boom"))
        self.assertFalse(Notification.objects.exists())

    def test_a_detached_standard_still_counts_when_it_failed_in_this_run(self):
        rows = [self._failed(0, "README present", attach=False)]
        self.policy.handle(self._event(rows, failed=1))
        self.assertEqual(Notification.objects.get().title, "1 standard failed")

    def test_a_run_with_no_failed_rows_raises_nothing(self):
        rows = [self._row(StandardExecution.Status.PASSED, 100)]
        self.policy.handle(self._event(rows, passed=1, failed=1))
        self.assertFalse(Notification.objects.exists())

    def test_the_triggering_user_is_recorded_for_routing(self):
        user = baker.make("app.User")
        rows = [self._failed(10, triggered_by_user=user)]
        self.policy.handle(self._event(rows, failed=1))
        self.assertEqual(Notification.objects.get().triggered_by_user_ids, [str(user.pk)])


class GraphBrokePolicyTests(_PolicyTestCase):
    policy = GraphBrokePolicy()

    def _event(self, had_worked_before=True, tenant_id=None):
        return DependencyInferenceFailed(
            project_id=str(self.project.pk),
            tenant_id=tenant_id or str(self.tenant.pk),
            error="LLM timed out\ntraceback...",
            had_worked_before=had_worked_before,
        )

    def test_a_map_that_used_to_build_raises_it(self):
        self.policy.handle(self._event())
        n = Notification.objects.get()
        self.assertEqual(n.kind, "graph.failed")
        self.assertEqual(n.body, "LLM timed out")

    def test_a_map_that_never_built_is_quiet(self):
        self.policy.handle(self._event(had_worked_before=False))
        self.assertFalse(Notification.objects.exists())

    def test_another_workspace_is_quiet(self):
        self.policy.handle(self._event(tenant_id=str(baker.make("app.Tenant").pk)))
        self.assertFalse(Notification.objects.exists())


class RegistrationTests(_PolicyTestCase):
    def test_published_events_reach_the_policies(self):
        event_bus.clear()
        subscribers.register()
        row = self._row(StandardExecution.Status.ERROR)

        event_bus.publish(self._event([row], errored=1, error="boom"))
        event_bus.publish(
            DependencyInferenceFailed(
                project_id=str(self.project.pk), tenant_id=str(self.tenant.pk),
                error="x", had_worked_before=True,
            )
        )

        self.assertEqual(
            sorted(Notification.objects.values_list("kind", flat=True)),
            ["graph.failed", "run.failed"],
        )
