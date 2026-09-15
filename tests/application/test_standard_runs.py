"""Background standard runs: ``enqueue_run`` + the ``run_standards`` job.

``enqueue_run`` creates the RUNNING rows and defers the job (the defer is
mocked here); the job fills those rows in. The sandbox runner is always
mocked — no container is ever started in tests.
"""
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock
from uuid import uuid4

import pytest
from django.test import TestCase, override_settings
from django.utils import timezone
from model_bakery import baker

from app import tasks
from app.application.standard_runs import enqueue_run, expire_stale_runs
from app.domain.models import StandardExecution
from tests.support import commit_status_patch, defer_patch

PASSED = {"passed": True, "score": 100, "message": "OK", "details": {}}
FAILED = {"passed": False, "score": 10, "message": "nope", "details": {}}


@contextmanager
def _mocked_runner(run_side_effect):
    """Patch the sandbox runner (and the token-fetching input config)."""
    runner = mock.Mock()
    runner.run.side_effect = run_side_effect
    with mock.patch(
        "app.application.standard_engine.SandboxRunner", return_value=runner
    ), mock.patch(
        "app.application.standard_engine.StandardEngine.build_input_config",
        return_value={},
    ), commit_status_patch():
        yield runner



@pytest.mark.django_db
class RunStandardsTaskTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant)

    def _standard(self, code):
        return baker.make("app.Standard", tenant=self.tenant, code=code)

    def _execution(self, standard, status=StandardExecution.Status.RUNNING):
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            event_type="manual",
            status=status,
        )

    def _run(self, executions):
        return tasks.run_standards.func(
            project_id=str(self.project.pk),
            execution_ids=[str(e.pk) for e in executions],
        )

    def test_rows_that_are_no_longer_running_are_skipped(self):
        running = self._execution(self._standard("A"))
        done = self._execution(self._standard("B"), StandardExecution.Status.PASSED)

        with _mocked_runner([PASSED]) as runner:
            self._run([running, done])

        assert runner.run.call_count == 1
        assert runner.run.call_args[0][0] == "A"
        running.refresh_from_db()
        done.refresh_from_db()
        assert running.status == StandardExecution.Status.PASSED
        assert done.status == StandardExecution.Status.PASSED
        assert done.message == ""

    def test_a_raising_runner_errors_remaining_rows_and_propagates(self):
        ok = self._execution(self._standard("A"))
        boom = self._execution(self._standard("B"))

        def run(code, _config):
            if code == "A":
                return dict(PASSED)
            raise RuntimeError("sandbox exploded")

        with _mocked_runner(run):
            with pytest.raises(RuntimeError):
                self._run([ok, boom])

        ok.refresh_from_db()
        boom.refresh_from_db()
        assert boom.status == StandardExecution.Status.ERROR
        assert boom.message == "sandbox exploded"
        assert boom.details == {"error": "sandbox exploded"}
        # Nothing is left hanging in RUNNING: rows the job never reached are
        # errored with the same failure (row order is the queryset's, so the
        # sibling is either its own PASSED result or that failure).
        assert not StandardExecution.objects.filter(
            status=StandardExecution.Status.RUNNING
        ).exists()
        assert ok.status in {
            StandardExecution.Status.PASSED,
            StandardExecution.Status.ERROR,
        }

    def test_normal_run_records_one_result_per_running_row(self):
        passing = self._execution(self._standard("A"))
        failing = self._execution(self._standard("B"))

        def run(code, _config):
            return dict(PASSED) if code == "A" else dict(FAILED)

        with _mocked_runner(run) as runner:
            self._run([passing, failing])

        assert runner.run.call_count == 2
        passing.refresh_from_db()
        failing.refresh_from_db()
        assert passing.status == StandardExecution.Status.PASSED
        assert passing.score == 100
        assert failing.status == StandardExecution.Status.FAILED
        assert failing.score == 10

    def test_vanished_project_leaves_other_projects_rows_alone(self):
        # The job only ever touches executions of its own project: the input
        # config it builds carries that project's token and LLM keys, so a
        # stray id from elsewhere must not be run — or even errored — with it.
        execution = self._execution(self._standard("A"))

        with _mocked_runner([PASSED]) as runner:
            tasks.run_standards.func(
                project_id=str(uuid4()), execution_ids=[str(execution.pk)]
            )

        runner.run.assert_not_called()
        execution.refresh_from_db()
        assert execution.status == StandardExecution.Status.RUNNING

    def test_executions_of_another_project_are_not_run(self):
        mine = self._execution(self._standard("A"))
        other_project = baker.make("app.Project", tenant=baker.make("app.Tenant"))
        theirs = baker.make(
            "app.StandardExecution",
            project=other_project,
            standard=baker.make("app.Standard", tenant=other_project.tenant, code="B"),
            standard_name="B",
            event_type="manual",
            status=StandardExecution.Status.RUNNING,
        )

        with _mocked_runner([PASSED]) as runner:
            self._run([mine, theirs])

        assert [c.args[0] for c in runner.run.call_args_list] == ["A"]
        theirs.refresh_from_db()
        assert theirs.status == StandardExecution.Status.RUNNING

    def test_deleted_standard_errors_its_row_and_the_rest_still_run(self):
        gone = self._execution(self._standard("A"))
        gone.standard.delete()  # FK is SET_NULL: the row stays, standard is None
        ok = self._execution(self._standard("B"))

        with _mocked_runner([PASSED]) as runner:
            self._run([gone, ok])

        assert runner.run.call_count == 1
        gone.refresh_from_db()
        ok.refresh_from_db()
        assert gone.status == StandardExecution.Status.ERROR
        assert gone.message == "standard no longer exists"
        assert gone.details == {"error": "standard no longer exists"}
        assert ok.status == StandardExecution.Status.PASSED


@pytest.mark.django_db
class StaleRunTests(TestCase):
    """RUNNING rows nobody will finish must not block re-runs or poll forever."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.standard = baker.make("app.Standard", tenant=self.tenant)

    def _running(self, age):
        row = baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=self.standard,
            standard_name=self.standard.name,
            event_type="manual",
            status=StandardExecution.Status.RUNNING,
        )
        StandardExecution.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - age
        )
        row.refresh_from_db()
        return row

    @override_settings(STANDARD_RUN_STALE_MINUTES=30)
    def test_expire_marks_only_rows_past_the_cutoff(self):
        old = self._running(timedelta(minutes=31))
        fresh = self._running(timedelta(minutes=29))

        assert expire_stale_runs() == 1

        old.refresh_from_db()
        fresh.refresh_from_db()
        assert old.status == StandardExecution.Status.ERROR
        assert "30 minutes" in old.message
        assert old.details == {"error": old.message}
        assert fresh.status == StandardExecution.Status.RUNNING
        assert tasks.expire_stale_standard_runs.func(timestamp=0) == 0

    @override_settings(STANDARD_RUN_STALE_MINUTES=30)
    def test_a_stale_row_does_not_count_as_already_running(self):
        self._running(timedelta(minutes=31))

        with defer_patch() as configure:
            summary = enqueue_run(self.project, [self.standard])

        assert summary["queued"] == 1
        assert summary["already_running"] == 0
        configure.return_value.defer.assert_called_once()

    @override_settings(STANDARD_RUN_STALE_MINUTES=30)
    def test_a_fresh_row_still_blocks_a_manual_re_run(self):
        self._running(timedelta(minutes=1))

        with defer_patch() as configure:
            summary = enqueue_run(self.project, [self.standard])

        assert summary["queued"] == 0
        assert summary["already_running"] == 1
        configure.assert_not_called()


@pytest.mark.django_db
class EnqueueRunTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="acme/app")

    def _standard(self, **kw):
        return baker.make("app.Standard", tenant=self.tenant, **kw)

    def test_creates_a_running_row_per_standard_and_defers_the_job(self):
        s1, s2 = self._standard(), self._standard()

        with defer_patch() as configure:
            summary = enqueue_run(self.project, [s1, s2])

        rows = StandardExecution.objects.filter(project=self.project)
        assert rows.count() == 2
        assert {r.status for r in rows} == {StandardExecution.Status.RUNNING}
        assert {r.standard_id for r in rows} == {s1.pk, s2.pk}
        assert all(r.event_type == "manual" for r in rows)
        assert all(r.triggered_by == "manual" for r in rows)

        configure.assert_called_once_with(lock=f"standards:{self.project.pk}")
        configure.return_value.defer.assert_called_once()
        kwargs = configure.return_value.defer.call_args.kwargs
        assert kwargs["project_id"] == str(self.project.pk)
        assert set(kwargs["execution_ids"]) == {str(r.pk) for r in rows}

        assert summary["queued"] == 2
        assert summary["already_running"] == 0
        assert summary["project_id"] == str(self.project.pk)
        assert summary["message"] == (
            "Queued 2 standards on acme/app. "
            "Results appear on the project page as they finish."
        )

    def test_standards_already_running_are_skipped(self):
        busy, idle = self._standard(), self._standard()
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=busy,
            status=StandardExecution.Status.RUNNING,
        )

        with defer_patch() as configure:
            summary = enqueue_run(self.project, [busy, idle])

        assert StandardExecution.objects.filter(
            project=self.project, standard=busy
        ).count() == 1
        new_rows = StandardExecution.objects.filter(
            project=self.project, standard=idle
        )
        assert new_rows.count() == 1
        kwargs = configure.return_value.defer.call_args.kwargs
        assert kwargs["execution_ids"] == [str(new_rows.get().pk)]
        assert summary["queued"] == 1
        assert summary["already_running"] == 1
        assert "1 already running" in summary["message"]

    def test_nothing_is_deferred_when_everything_is_alreadyrunning_executions(self):
        busy = self._standard()
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=busy,
            status=StandardExecution.Status.RUNNING,
        )

        with defer_patch() as configure:
            summary = enqueue_run(self.project, [busy])

        configure.assert_not_called()
        assert summary["queued"] == 0
        assert summary["already_running"] == 1

    def test_a_failed_defer_leaves_no_running_rows_behind(self):
        # Rows and job are one savepoint: if the queue insert fails, the
        # RUNNING rows must roll back too, or nothing would ever finish them
        # and the standard would read as "already running" forever.
        standard = baker.make("app.Standard", tenant=self.tenant)

        with defer_patch() as configure:
            configure.return_value.defer.side_effect = RuntimeError("queue down")
            with pytest.raises(RuntimeError):
                enqueue_run(self.project, [standard])

        assert not StandardExecution.objects.filter(project=self.project).exists()

    def test_no_standards_is_a_noop(self):
        with defer_patch() as configure:
            assert enqueue_run(self.project, []) is None
        configure.assert_not_called()
        assert StandardExecution.objects.filter(project=self.project).count() == 0

    def test_triggered_by_and_user_are_recorded(self):
        user = baker.make("app.User")
        standard = self._standard()

        with defer_patch():
            enqueue_run(self.project, [standard], triggered_by="attached", user=user)

        row = StandardExecution.objects.get(project=self.project)
        assert row.triggered_by == "attached"
        assert row.triggered_by_user == user
