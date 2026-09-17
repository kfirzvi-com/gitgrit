"""Map-worker scenarios, group C: worker death, the recovery sweep, and
several workers sharing locks. Checked against the REAL Procrastinate schema.

Invariants asserted throughout:

* after a sweep or a processed job, no row is left in ``doing`` unless a live
  worker is actually running it;
* at most one ``todo`` row per queueing_lock;
* a graph job never moves ``doing`` -> ``todo`` (no ``deferred_for_retry``
  event). The one sanctioned exception is the sweep's explicit requeue of a
  dead-worker orphan that has no queued twin (scenarios 1, 5, 6), which it
  performs deliberately and only when no twin can collide.

TransactionTestCase, same reasons as ``test_job_zombie_invariants``.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

from django.test import TransactionTestCase
from model_bakery import baker
from procrastinate import exceptions, jobs
from procrastinate import worker as worker_module
from procrastinate.contrib.django import app as procrastinate_app
from procrastinate.job_context import AbortReason, JobContext

from app import tasks
from app.domain.models import Project
from tests.application.test_job_zombie_invariants import (
    QUEUE,
    TASK,
    CleanProcrastinateTables,
    _doing_jobs,
    _job,
    _next_fetchable_job_id,
    _register_worker,
    _sql,
)

TEN_MINUTES_AGO = "now() - interval '10 minutes'"


def _stale_worker() -> int:
    """A worker row whose heartbeat is long past ``STALE_WORKER_SECONDS``."""
    return _sql(
        f"INSERT INTO procrastinate_workers (last_heartbeat) VALUES ({TEN_MINUTES_AGO}) RETURNING id"
    )[0][0]


def _insert(*, status, lock, queueing_lock, task_name=TASK, queue=QUEUE, args="{}", worker_id=None):
    """Like ``_insert_job`` but with an independent ``queueing_lock`` (may be NULL)."""
    return _sql(
        "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, queueing_lock, "
        "args, status, worker_id) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s) RETURNING id",
        [queue, task_name, lock, queueing_lock, args, status, worker_id],
    )[0][0]


def _fetch(worker_id: int, queue: str = QUEUE) -> int | None:
    """A real fetch: the returned job IS moved to ``doing`` on ``worker_id``."""
    rows = _sql("SELECT id FROM procrastinate_fetch_job_v2(ARRAY[%s]::varchar[], %s)", [queue, worker_id])
    return rows[0][0] if rows and rows[0][0] is not None else None


def _events(job_id: int) -> list[str]:
    return [r[0] for r in _sql(
        "SELECT type FROM procrastinate_events WHERE job_id = %s ORDER BY id", [job_id]
    )]


def _todo_count(queueing_lock: str) -> int:
    return _sql(
        "SELECT count(*) FROM procrastinate_jobs WHERE queueing_lock = %s AND status = 'todo'",
        [queueing_lock],
    )[0][0]


def _worker_exists(worker_id: int) -> bool:
    return bool(_sql("SELECT 1 FROM procrastinate_workers WHERE id = %s", [worker_id]))


def _sweep() -> int:
    return asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))


class _ProjectMixin:
    def setUp(self):
        super().setUp()
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        self.project = baker.make("app.Project", tenant=tenant, platform_connection=conn)
        self.lock = f"project:{self.project.id}"
        self.qlock = f"deps:{self.project.id}"
        self.args = f'{{"project_id": "{self.project.id}"}}'

    def _process(self, job_id: int, *, inference, sleep=None, abort_reason=None) -> None:
        """Run Procrastinate's real ``Worker._process_job`` on ``job_id``.

        ``inference`` is the ``infer_and_store`` side effect (callable or
        exception); ``sleep`` replaces ``tasks._sleep`` (default: no-op).
        """
        worker = worker_module.Worker(procrastinate_app, queues=[QUEUE], install_signal_handlers=False)
        job = jobs.Job(
            id=job_id,
            status="doing",
            queue=QUEUE,
            lock=self.lock,
            queueing_lock=self.qlock,
            task_name=TASK,
            task_kwargs={"project_id": str(self.project.id)},
            attempts=0,
        )
        context = JobContext(
            app=procrastinate_app,
            worker_name="test-worker",
            worker_queues=[QUEUE],
            job=job,
            start_timestamp=time.time(),
            abort_reason=lambda: abort_reason,
        )
        with patch("app.application.dependency_agent.infer_and_store") as run, patch(
            "app.tasks._sleep", side_effect=sleep or (lambda s: None)
        ):
            run.side_effect = inference
            asyncio.run(worker._process_job(context))

    def _succeed(self, project):
        Project.objects.filter(pk=project.pk).update(deps_status=Project.DepsStatus.OK)


class DeadWorkerSweepTests(_ProjectMixin, CleanProcrastinateTables, TransactionTestCase):
    def test_1_orphan_without_twin_is_requeued_and_runs_on_a_live_worker(self):
        dead = _stale_worker()
        orphan = _insert(status="doing", lock=self.lock, queueing_lock=self.qlock, args=self.args, worker_id=dead)
        live = _register_worker()
        fresh = _insert(status="doing", lock="project:other", queueing_lock="deps:other", worker_id=live)

        self.assertEqual(_sweep(), 1)

        self.assertEqual(_job(orphan)["status"], "todo")  # sanctioned doing -> todo: dead worker, no twin
        self.assertEqual(_job(fresh)["status"], "doing", "job on a live worker must be left alone")
        self.assertFalse(_worker_exists(dead), "stale worker row should be pruned")

        self.assertEqual(_fetch(live), orphan)
        self._process(orphan, inference=self._succeed)
        self.assertEqual(_job(orphan)["status"], "succeeded")
        self.assertEqual(_doing_jobs(self.qlock), [])
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.OK)

    def test_2_orphan_with_twin_is_failed_and_twin_runs(self):
        dead = _stale_worker()
        orphan = _insert(status="doing", lock=self.lock, queueing_lock=self.qlock, args=self.args, worker_id=dead)
        twin = _insert(status="todo", lock=self.lock, queueing_lock=self.qlock, args=self.args)

        self.assertEqual(_sweep(), 1)

        self.assertEqual(_job(orphan)["status"], "failed")
        self.assertNotIn("deferred_for_retry", _events(orphan))
        live = _register_worker()
        self.assertEqual(_fetch(live), twin)
        self._process(twin, inference=self._succeed)
        self.assertEqual(_job(twin)["status"], "succeeded")
        self.assertEqual(_doing_jobs(self.qlock), [])

    def test_3_sweep_race_with_a_late_twin_self_heals_on_the_next_sweep(self):
        """The twin appears after the sweep's twin check and before its
        requeue: the requeue collides with the twin's ``todo`` row. That must
        be contained to this job and repaired by the following sweep."""
        orphan = _insert(status="doing", lock=self.lock, queueing_lock=self.qlock, args=self.args)
        twin = _insert(status="todo", lock=self.lock, queueing_lock=self.qlock, args=self.args)

        async def no_twin_seen(**kwargs):
            return []

        with patch.object(procrastinate_app.job_manager, "list_jobs_async", side_effect=no_twin_seen):
            handled = _sweep()  # must not raise

        self.assertEqual(handled, 0, "the collided job must not be counted as handled")
        self.assertEqual(_job(orphan)["status"], "doing", "collision leaves the orphan where it was")
        self.assertEqual(_job(twin)["status"], "todo")
        self.assertEqual(_todo_count(self.qlock), 1)

        self.assertEqual(_sweep(), 1)  # unpatched: sees the twin, fails the orphan

        self.assertEqual(_job(orphan)["status"], "failed")
        self.assertEqual(_next_fetchable_job_id(_register_worker()), twin)
        self.assertEqual(_doing_jobs(self.qlock), [])


class MultiWorkerTests(_ProjectMixin, CleanProcrastinateTables, TransactionTestCase):
    def test_4_same_lock_is_fetched_by_one_worker_at_a_time(self):
        w1, w2 = _register_worker(), _register_worker()
        first = _insert(status="todo", lock=self.lock, queueing_lock=self.qlock, args=self.args)
        # a second todo on the same queueing_lock would violate the index; use a
        # different queueing_lock but the SAME serialization lock.
        second = _insert(status="todo", lock=self.lock, queueing_lock=f"{self.qlock}:manual", args=self.args)

        self.assertEqual(_fetch(w1), first)
        self.assertIsNone(_fetch(w2), "same lock: second worker must get nothing while first is doing")

        _sql("SELECT procrastinate_finish_job_v1(%s, 'succeeded', false)", [first])
        self.assertEqual(_fetch(w2), second)
        self.assertEqual(_doing_jobs(self.qlock), [])

    def test_4b_different_locks_are_fetched_by_both_workers(self):
        w1, w2 = _register_worker(), _register_worker()
        a = _insert(status="todo", lock="project:a", queueing_lock="deps:a")
        b = _insert(status="todo", lock="project:b", queueing_lock="deps:b")

        self.assertEqual(_fetch(w1), a)
        self.assertEqual(_fetch(w2), b)
        self.assertEqual(_job(a)["worker_id"], w1)
        self.assertEqual(_job(b)["worker_id"], w2)


class SweepHygieneTests(_ProjectMixin, CleanProcrastinateTables, TransactionTestCase):
    def test_5_sweep_is_idempotent_and_prunes_stale_workers(self):
        dead = _stale_worker()
        orphan = _insert(status="doing", lock=self.lock, queueing_lock=self.qlock, args=self.args, worker_id=dead)

        self.assertEqual(_sweep(), 1)
        self.assertEqual(_job(orphan)["status"], "todo")
        self.assertFalse(_worker_exists(dead))

        self.assertEqual(_sweep(), 0, "nothing left to handle")
        self.assertEqual(_job(orphan)["status"], "todo")
        self.assertEqual(_job(orphan)["attempts"], 1, "requeued exactly once")
        self.assertEqual(_todo_count(self.qlock), 1)

    def test_6_orphan_of_another_task_is_requeued_without_touching_graph_jobs(self):
        standards_orphan = _insert(
            status="doing", lock="standards:p1", queueing_lock=None,
            task_name="run_standards", queue="standards",
            args='{"project_id": "p1", "execution_ids": []}',
        )
        live = _register_worker()
        graph_running = _insert(status="doing", lock=self.lock, queueing_lock=self.qlock, args=self.args, worker_id=live)
        graph_queued = _insert(status="todo", lock="project:q", queueing_lock="deps:q")

        self.assertEqual(_sweep(), 1)

        self.assertEqual(_job(standards_orphan)["status"], "todo")
        self.assertEqual(_job(graph_running)["status"], "doing")
        self.assertEqual(_job(graph_queued)["status"], "todo")
        self.assertEqual(_fetch(live, queue="standards"), standards_orphan)


class ZombieReplayTests(_ProjectMixin, CleanProcrastinateTables, TransactionTestCase):
    def test_7_staging_incident_replayed_against_the_new_code(self):
        """Yesterday on staging: job 71109 ``doing`` on a live worker, twin
        71112 ``todo``, the run failed, and the retry collided. With in-task
        retries the first job must end ``failed`` and the twin must run."""
        live = _register_worker()
        first = _insert(status="doing", lock=self.lock, queueing_lock=self.qlock, args=self.args, worker_id=live)
        twin = _insert(status="todo", lock=self.lock, queueing_lock=self.qlock, args=self.args)

        self._process(first, inference=RuntimeError("429 credits depleted"))

        self.assertEqual(_job(first)["status"], "failed")
        self.assertEqual(_job(first)["attempts"], 1, "finish bumps attempts once")
        self.assertEqual(_doing_jobs(self.qlock), [])
        self.assertEqual(_fetch(live), twin)

        self._process(twin, inference=self._succeed)

        self.assertEqual(_job(twin)["status"], "succeeded")
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.OK)
        for job_id in (first, twin):
            self.assertNotIn("deferred_for_retry", _events(job_id))
        self.assertEqual(_todo_count(self.qlock), 0)


class ShutdownDuringRetryPauseTests(_ProjectMixin, CleanProcrastinateTables, TransactionTestCase):
    """The worker is asked to stop while the task is in its in-process retry
    pause. Whatever propagates, the row must end terminal, never ``todo``."""

    def _run_interrupted(self, exc, abort_reason):
        live = _register_worker()
        job = _insert(status="doing", lock=self.lock, queueing_lock=self.qlock, args=self.args, worker_id=live)

        def interrupted_sleep(seconds):
            raise exc

        self._process(job, inference=RuntimeError("blip"), sleep=interrupted_sleep, abort_reason=abort_reason)
        return job, live

    def _assert_terminal_and_unblocked(self, job, live):
        status = _job(job)["status"]
        self.assertIn(status, ("aborted", "failed"), f"job left in {status!r}")
        self.assertNotIn("deferred_for_retry", _events(job))
        self.assertEqual(_doing_jobs(self.qlock), [])
        # A new event can proceed: a fresh job on the same locks is fetchable.
        fresh = _insert(status="todo", lock=self.lock, queueing_lock=self.qlock, args=self.args)
        self.assertEqual(_next_fetchable_job_id(live), fresh)

    def test_8a_job_aborted_for_shutdown_ends_terminal(self):
        job, live = self._run_interrupted(exceptions.JobAborted(), AbortReason.SHUTDOWN)
        self._assert_terminal_and_unblocked(job, live)

    def test_8b_job_aborted_by_user_request_ends_terminal(self):
        job, live = self._run_interrupted(exceptions.JobAborted(), AbortReason.USER_REQUEST)
        self._assert_terminal_and_unblocked(job, live)

    def test_8c_cancelled_error_during_pause_ends_terminal(self):
        job, live = self._run_interrupted(asyncio.CancelledError(), AbortReason.SHUTDOWN)
        self._assert_terminal_and_unblocked(job, live)
