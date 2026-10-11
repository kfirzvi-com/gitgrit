"""``run_standards`` publishes ``StandardRunFinished`` once per run.

The notification center listens for it; the worker only publishes. The
sandbox runner is always mocked — no container is ever started in tests.
"""
from contextlib import contextmanager
from unittest import mock
from uuid import uuid4

import pytest
from django.test import TestCase
from model_bakery import baker

from app import tasks
from app.application import event_bus, subscribers
from app.domain.events import StandardRunFinished
from app.domain.models import StandardExecution

PASSED = {"passed": True, "score": 100, "message": "OK", "details": {}}
FAILED = {"passed": False, "score": 10, "message": "nope", "details": {}}


@contextmanager
def _mocked_runner(run_side_effect, input_config=None):
    """Patch the sandbox runner and the token-fetching input config."""
    runner = mock.Mock()
    runner.run.side_effect = run_side_effect
    with mock.patch(
        "app.application.standard_engine.SandboxRunner", return_value=runner
    ), mock.patch(
        "app.application.standard_engine.StandardEngine.build_input_config",
        **(input_config or {"return_value": {}}),
    ):
        yield runner


@pytest.mark.django_db
class RunStandardsPublishesTests(TestCase):
    def setUp(self):
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        self.events = []
        event_bus.subscribe(StandardRunFinished, self.events.append)
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant)

    def _execution(self, code):
        standard = baker.make("app.Standard", tenant=self.tenant, code=code)
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            event_type="manual",
            status=StandardExecution.Status.RUNNING,
        )

    def _run(self, executions, project_id=None):
        return tasks.run_standards.func(
            project_id=project_id or str(self.project.pk),
            execution_ids=[str(e.pk) for e in executions],
        )

    def test_finished_run_publishes_its_counts(self):
        passing = self._execution("A")
        failing = self._execution("B")

        def run(code, _config):
            return dict(PASSED) if code == "A" else dict(FAILED)

        with _mocked_runner(run):
            self._run([passing, failing])

        assert len(self.events) == 1
        event = self.events[0]
        assert event.project_id == str(self.project.pk)
        assert event.tenant_id == str(self.tenant.pk)
        assert set(event.execution_ids) == {str(passing.pk), str(failing.pk)}
        assert (event.passed, event.failed, event.errored) == (1, 1, 0)
        assert event.error == ""

    def test_job_failure_errors_rows_reraises_and_publishes(self):
        first = self._execution("A")
        second = self._execution("B")

        with _mocked_runner(
            [], input_config={"side_effect": RuntimeError("token fetch failed")}
        ):
            with pytest.raises(RuntimeError):
                self._run([first, second])

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.status == StandardExecution.Status.ERROR
        assert second.status == StandardExecution.Status.ERROR
        assert len(self.events) == 1
        event = self.events[0]
        assert event.tenant_id == str(self.tenant.pk)
        assert set(event.execution_ids) == {str(first.pk), str(second.pk)}
        assert (event.passed, event.failed, event.errored) == (0, 0, 2)
        assert "token fetch failed" in event.error

    def test_missing_project_publishes_nothing(self):
        execution = self._execution("A")

        with _mocked_runner([PASSED]):
            self._run([execution], project_id=str(uuid4()))

        assert self.events == []
