"""``infer_project_dependencies`` publishes ``DependencyInferenceFailed`` once
its in-process retries are exhausted.

The notification center listens for it; the worker only publishes.
"""
from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app import tasks
from app.application import event_bus, subscribers
from app.domain.events import DependencyInferenceFailed
from tests.support import MonkeyPatchMixin


class InferPublishesTests(MonkeyPatchMixin, TestCase):
    def setUp(self):
        super().setUp()
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        self.events = []
        event_bus.subscribe(DependencyInferenceFailed, self.events.append)
        self.monkeypatch.setattr(tasks, "_sleep", lambda seconds: None)

    def _project(self, **fields):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        return baker.make("app.Project", tenant=tenant, platform_connection=conn, **fields)

    def _inference(self, outcomes):
        """Stub ``infer_and_store``; each call pops the next outcome, an
        exception instance to raise or anything else to return."""

        def fake(project):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        self.monkeypatch.setattr("app.application.dependency_agent.infer_and_store", fake)

    def test_exhausted_retries_publish_once_for_a_project_that_had_a_map(self):
        project = self._project(deps_analyzed_at=timezone.now())
        self._inference([RuntimeError("provider said no")] * tasks.INFERENCE_ATTEMPTS)

        with self.assertRaises(RuntimeError):
            tasks.infer_project_dependencies.func(project_id=str(project.id))

        self.assertEqual(
            self.events,
            [
                DependencyInferenceFailed(
                    project_id=str(project.id),
                    tenant_id=str(project.tenant_id),
                    error="provider said no",
                    had_worked_before=True,
                )
            ],
        )

    def test_never_analyzed_project_publishes_had_worked_before_false(self):
        project = self._project(deps_analyzed_at=None)
        self._inference([RuntimeError("no model")] * tasks.INFERENCE_ATTEMPTS)

        with self.assertRaises(RuntimeError):
            tasks.infer_project_dependencies.func(project_id=str(project.id))

        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].error, "no model")
        self.assertFalse(self.events[0].had_worked_before)

    def test_failing_twice_then_succeeding_publishes_nothing(self):
        project = self._project(deps_analyzed_at=timezone.now())
        self._inference([RuntimeError("blip"), RuntimeError("blip"), None])

        tasks.infer_project_dependencies.func(project_id=str(project.id))

        self.assertEqual(self.events, [])

    def test_missing_project_publishes_nothing(self):
        self._inference([])

        tasks.infer_project_dependencies.func(project_id="00000000-0000-0000-0000-000000000000")

        self.assertEqual(self.events, [])
