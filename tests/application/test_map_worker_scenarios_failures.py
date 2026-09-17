"""Map-worker scenarios, group B: failures INSIDE ``infer_project_dependencies``.

Each scenario drives Procrastinate's real ``Worker._process_job`` over real
``procrastinate_jobs`` rows and asserts the invariants that keep the map
worker from wedging:

* no row is left in ``doing`` once processing returns;
* the job never moves ``doing`` -> ``todo`` (no ``deferred_for_retry`` event);
* at most one ``todo`` row per queueing_lock, and it is fetchable afterwards;
* the project's ``deps_status`` ends terminal.
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

from django.test import TransactionTestCase
from model_bakery import baker
from procrastinate import exceptions, jobs
from procrastinate import worker as worker_module
from procrastinate.contrib.django import app as procrastinate_app
from procrastinate.job_context import AbortReason, JobContext

from app import tasks
from app.application.subscribers import _enqueue_dependency_refresh
from app.domain.models import LLMRole, Project
from tests.application.test_job_zombie_invariants import (
    QUEUE,
    TASK,
    CleanProcrastinateTables,
    _job,
    _next_fetchable_job_id,
    _register_worker,
    _sql,
)


def _event_types(job_id: int) -> list[str]:
    return [r[0] for r in _sql(
        "SELECT type FROM procrastinate_events WHERE job_id = %s ORDER BY id", [job_id]
    )]


def _rows(queueing_lock: str) -> dict[int, str]:
    return dict(_sql(
        "SELECT id, status FROM procrastinate_jobs WHERE queueing_lock = %s ORDER BY id",
        [queueing_lock],
    ))


class FailureScenarioBase(CleanProcrastinateTables, TransactionTestCase):
    def setUp(self):
        super().setUp()
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        self.tenant = tenant
        self.project = baker.make("app.Project", tenant=tenant, platform_connection=conn)
        self.lock = f"project:{self.project.id}"
        self.queueing_lock = f"deps:{self.project.id}"
        self.worker_id = _register_worker()

    # -- job plumbing ------------------------------------------------------

    def _insert_doing(self, project_id=None) -> int:
        """A job a worker has already fetched, exactly as ``subscribers`` defers it."""
        pid = str(project_id or self.project.id)
        return _sql(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, queueing_lock, args, "
            "status, worker_id) VALUES (%s, %s, %s, %s, %s::jsonb, 'doing', %s) RETURNING id",
            [QUEUE, TASK, f"project:{pid}", f"deps:{pid}", json.dumps({"project_id": pid}),
             self.worker_id],
        )[0][0]

    def _process(self, job_id: int, inference, *, sleep=None, abort_reason=None) -> None:
        """Run ``job_id`` through Procrastinate's real worker code path with
        ``infer_and_store`` replaced by ``inference`` and the retry pause by
        ``sleep`` (default: no-op)."""
        worker = worker_module.Worker(
            procrastinate_app, queues=[QUEUE], install_signal_handlers=False
        )
        row = _sql(
            "SELECT lock, queueing_lock, args FROM procrastinate_jobs WHERE id = %s", [job_id]
        )[0]
        job = jobs.Job(
            id=job_id, status="doing", queue=QUEUE, lock=row[0], queueing_lock=row[1],
            task_name=TASK, attempts=0,
            task_kwargs=row[2] if isinstance(row[2], dict) else json.loads(row[2]),
        )
        context = JobContext(
            app=procrastinate_app, worker_name="test-worker", worker_queues=[QUEUE],
            job=job, start_timestamp=time.time(), abort_reason=lambda: abort_reason,
        )
        with patch("app.application.dependency_agent.infer_and_store", side_effect=inference), \
             patch("app.tasks._sleep", side_effect=sleep or (lambda s: None)):
            asyncio.run(worker._process_job(context))

    def _process_new_job(self, job_id, inference):
        """Fetch ``job_id`` the way a worker would (todo -> doing) and process it."""
        fetched = _sql(
            "SELECT id FROM procrastinate_fetch_job_v2(ARRAY[%s]::varchar[], %s)",
            [QUEUE, self.worker_id],
        )[0][0]
        self.assertEqual(fetched, job_id)
        self._process(job_id, inference)

    # -- fakes --------------------------------------------------------------

    def _fail_always(self, message="provider said no"):
        calls = []

        def boom(project):
            calls.append(1)
            raise RuntimeError(message)

        boom.calls = calls
        return boom

    def _succeed(self):
        def ok(project):
            Project.objects.filter(pk=project.pk).update(deps_status=Project.DepsStatus.OK)

        return ok

    # -- invariants ---------------------------------------------------------

    def assert_invariants(self, job_id: int, *, project_alive=True):
        rows = _rows(self.queueing_lock)
        self.assertNotIn("doing", rows.values(), f"row left in doing: {rows}")
        self.assertLessEqual(list(rows.values()).count("todo"), 1, rows)
        self.assertNotIn("deferred_for_retry", _event_types(job_id))
        self.assertNotEqual(_job(job_id)["status"], "todo")
        if project_alive:
            self.project.refresh_from_db()
            terminal = {Project.DepsStatus.OK, Project.DepsStatus.FAILED}
            if "todo" in rows.values():
                terminal.add(Project.DepsStatus.PENDING)
            self.assertIn(self.project.deps_status, terminal)


class InJobFailureScenarioTests(FailureScenarioBase):
    def test_1_all_attempts_fail_then_a_new_event_starts_fresh(self):
        doing = self._insert_doing()
        boom = self._fail_always()

        self._process(doing, boom)

        self.assertEqual(len(boom.calls), tasks.INFERENCE_ATTEMPTS)
        self.assertEqual(_job(doing)["status"], "failed")
        self.assert_invariants(doing)
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.FAILED)
        self.assertIn("provider said no", self.project.deps_error)

        # A later push enqueues a fresh job, which is immediately fetchable ...
        _enqueue_dependency_refresh(str(self.project.id))
        rows = _rows(self.queueing_lock)
        (fresh,) = [jid for jid, st in rows.items() if st == "todo"]
        self.assertEqual(_next_fetchable_job_id(self.worker_id), fresh)
        # ... and runs to success.
        self._process_new_job(fresh, self._succeed())
        self.assertEqual(_job(fresh)["status"], "succeeded")
        self.assert_invariants(fresh)
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.OK)

    def test_2_transient_failure_then_success(self):
        doing = self._insert_doing()
        outcomes = [RuntimeError("blip"), None]

        def flaky(project):
            outcome = outcomes.pop(0)
            if outcome:
                raise outcome
            self._succeed()(project)

        self._process(doing, flaky)

        self.assertEqual(outcomes, [])
        self.assertEqual(_job(doing)["status"], "succeeded")
        self.assertEqual(len(_rows(self.queueing_lock)), 1)
        self.assert_invariants(doing)
        self.assertEqual(self.project.deps_status, Project.DepsStatus.OK)
        self.assertEqual(self.project.deps_error, "")

    def test_3_twin_deferred_during_the_retry_pause_is_fetchable_afterwards(self):
        doing = self._insert_doing()
        deferred = []

        def defer_twin_instead_of_sleeping(seconds):
            if not deferred:
                _enqueue_dependency_refresh(str(self.project.id))
                deferred.append(1)

        self._process(doing, self._fail_always(), sleep=defer_twin_instead_of_sleeping)

        self.assertEqual(_job(doing)["status"], "failed")
        rows = _rows(self.queueing_lock)
        (twin,) = [jid for jid, st in rows.items() if st == "todo"]
        self.assertEqual(_next_fetchable_job_id(self.worker_id), twin)
        self.assert_invariants(doing)

    def test_4_project_deleted_while_job_is_todo(self):
        # Deferred like a real event, then the project disappears before a
        # worker picks the job up.
        _enqueue_dependency_refresh(str(self.project.id))
        (todo,) = _rows(self.queueing_lock)
        self.project.delete()
        calls = []

        self._process_new_job(todo, lambda p: calls.append(1))

        self.assertEqual(calls, [], "inference must not run for a vanished project")
        self.assertEqual(_job(todo)["status"], "succeeded")
        self.assert_invariants(todo, project_alive=False)

    def test_5_project_deleted_while_job_is_doing(self):
        doing = self._insert_doing()
        calls = []

        def delete_then_fail(project):
            calls.append(1)
            Project.objects.filter(pk=project.pk).delete()
            raise RuntimeError("repo vanished mid-run")

        self._process(doing, delete_then_fail)

        # The in-task retries keep going against the stale instance (the
        # bookkeeping UPDATEs match zero rows and do not raise); the job then
        # ends failed and nothing is left behind.
        self.assertEqual(len(calls), tasks.INFERENCE_ATTEMPTS)
        self.assertEqual(_job(doing)["status"], "failed")
        self.assertFalse(Project.objects.filter(pk=self.project.pk).exists())
        self.assert_invariants(doing, project_alive=False)

    def test_6a_job_aborted_on_shutdown_ends_aborted_never_todo(self):
        """An aborted job is TERMINAL: ``fetch_job`` only ever selects ``todo``
        rows, so nothing re-runs it. A later event (push, re-add) enqueues a
        fresh job. Note ``JobAborted`` is an ``Exception`` subclass, so the
        task's own retry loop catches and retries it before re-raising on the
        last attempt; the task takes no context, so a cooperative abort can
        never actually reach it — this documents the behavior, it is not a
        stuck path."""
        doing = self._insert_doing()
        calls = []

        def aborted(project):
            calls.append(1)
            raise exceptions.JobAborted()

        self._process(doing, aborted, abort_reason=AbortReason.SHUTDOWN)

        self.assertEqual(len(calls), tasks.INFERENCE_ATTEMPTS)
        self.assertEqual(_job(doing)["status"], "aborted")
        self.assertIn("aborted", _event_types(doing))
        self.assert_invariants(doing)
        self.assertIsNone(tasks.infer_project_dependencies.retry_strategy)

    def test_6b_job_aborted_by_user_request_ends_aborted(self):
        doing = self._insert_doing()

        def aborted(project):
            raise exceptions.JobAborted()

        self._process(doing, aborted, abort_reason=AbortReason.USER_REQUEST)

        self.assertEqual(_job(doing)["status"], "aborted")
        self.assert_invariants(doing)

    def test_6c_cancellation_mid_run_ends_aborted(self):
        """What a real shutdown looks like from the worker's side: the awaiting
        coroutine sees ``CancelledError``. It is a ``BaseException``, so the
        task's retry loop never sees it and its FAILED bookkeeping does not run:
        the job row ends ``aborted`` (terminal, queue is clean) but the project
        stays ``running`` until the next event resets it. Display gap only."""
        doing = self._insert_doing()

        def cancelled(project):
            raise asyncio.CancelledError()

        self._process(doing, cancelled)

        self.assertEqual(_job(doing)["status"], "aborted")
        self.assertNotIn("doing", _rows(self.queueing_lock).values())
        self.assertNotIn("deferred_for_retry", _event_types(doing))
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.RUNNING)

    def test_7_exception_in_failure_bookkeeping_still_ends_the_job(self):
        doing = self._insert_doing()
        real_filter = Project.objects.filter
        raised = []

        class _BrokenOnFailedWrite:
            def __init__(self, qs):
                self._qs = qs

            def update(self, **kwargs):
                if kwargs.get("deps_status") == Project.DepsStatus.FAILED:
                    raised.append(1)
                    raise RuntimeError("database went away during bookkeeping")
                return self._qs.update(**kwargs)

            def __getattr__(self, name):
                return getattr(self._qs, name)

        with patch.object(Project.objects, "filter", lambda *a, **k: _BrokenOnFailedWrite(real_filter(*a, **k))):
            self._process(doing, self._fail_always())

        self.assertEqual(raised, [1])
        self.assertEqual(_job(doing)["status"], "failed")
        self.assertNotIn("doing", _rows(self.queueing_lock).values())
        self.assertNotIn("deferred_for_retry", _event_types(doing))
        # The FAILED write was the one that blew up, so the project is left
        # RUNNING — the job row itself is terminal, which is what matters for
        # the queue; the next event resets deps_status to PENDING.
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.RUNNING)

    def test_8_no_reasoning_role_fails_fast_with_the_real_agent(self):
        self.assertEqual(LLMRole.objects.filter(tenant=self.tenant).count(), 0)
        doing = self._insert_doing()
        worker = worker_module.Worker(
            procrastinate_app, queues=[QUEUE], install_signal_handlers=False
        )
        job = jobs.Job(
            id=doing, status="doing", queue=QUEUE, lock=self.lock,
            queueing_lock=self.queueing_lock, task_name=TASK,
            task_kwargs={"project_id": str(self.project.id)}, attempts=0,
        )
        context = JobContext(
            app=procrastinate_app, worker_name="test-worker", worker_queues=[QUEUE],
            job=job, start_timestamp=time.time(), abort_reason=lambda: None,
        )
        with patch("app.tasks._sleep") as sleep:
            asyncio.run(worker._process_job(context))  # real infer_and_store

        self.assertEqual(sleep.call_count, tasks.INFERENCE_ATTEMPTS - 1)
        self.assertEqual(_job(doing)["status"], "failed")
        self.assert_invariants(doing)
        self.assertEqual(self.project.deps_status, Project.DepsStatus.FAILED)
        self.assertIn("No 'reasoning' LLM role configured", self.project.deps_error)

    def test_9_base_exception_escaping_the_task_still_ends_the_job(self):
        """``KeyboardInterrupt`` is not an ``Exception``, so the task's retry
        loop does not catch it. Procrastinate's worker catches ``BaseException``
        and finishes the job as failed."""
        doing = self._insert_doing()
        calls = []

        def interrupt(project):
            calls.append(1)
            raise KeyboardInterrupt()

        self._process(doing, interrupt)

        self.assertEqual(calls, [1], "no in-task retry for a BaseException")
        self.assertEqual(_job(doing)["status"], "failed")
        self.assertNotIn("doing", _rows(self.queueing_lock).values())
        self.assertNotIn("deferred_for_retry", _event_types(doing))
