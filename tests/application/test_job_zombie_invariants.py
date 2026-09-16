"""Zombie-job invariants, checked against the REAL Procrastinate schema.

Twice, graph jobs got stuck in ``doing`` forever ("zombies") because a retry
or a recovery requeue collided with Procrastinate's one-``todo``-per-
queueing_lock index. The unit tests mock the job manager, so they would keep
passing if the library changed or the same mistake crept into another path.
These tests run the library's own SQL functions and worker code on the test
database, so they fail on the behavior, not on the wording of the fix.

TransactionTestCase: Procrastinate's Django connector runs its queries via
``sync_to_async`` on another thread, whose DB connection cannot see rows from
an uncommitted test transaction.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from model_bakery import baker
from procrastinate import jobs, worker as worker_module
from procrastinate.contrib.django import app as procrastinate_app
from procrastinate.job_context import JobContext

from app import tasks

TASK = "infer_project_dependencies"
QUEUE = "graph"


def _sql(query, params=()):
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall() if cursor.description else None


def _register_worker() -> int:
    return _sql("INSERT INTO procrastinate_workers DEFAULT VALUES RETURNING id")[0][0]


def _insert_job(*, status, lock, args="{}", worker_id=None, task_name=TASK) -> int:
    return _sql(
        "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, queueing_lock, "
        "args, status, worker_id) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s) RETURNING id",
        [QUEUE, task_name, lock, lock, args, status, worker_id],
    )[0][0]


def _job(job_id: int) -> dict:
    row = _sql(
        "SELECT status, attempts, scheduled_at, worker_id FROM procrastinate_jobs WHERE id = %s",
        [job_id],
    )[0]
    return dict(zip(("status", "attempts", "scheduled_at", "worker_id"), row))


def _next_fetchable_job_id(worker_id: int) -> int | None:
    """What a worker would pick up next — probed inside a rolled-back
    transaction so the probe itself never moves a job to ``doing``."""
    with transaction.atomic():
        rows = _sql(
            "SELECT id FROM procrastinate_fetch_job_v2(ARRAY[%s]::varchar[], %s)",
            [QUEUE, worker_id],
        )
        transaction.set_rollback(True)
    return rows[0][0] if rows and rows[0][0] is not None else None


def _doing_jobs(lock: str) -> list[int]:
    return [r[0] for r in _sql(
        "SELECT id FROM procrastinate_jobs WHERE queueing_lock = %s AND status = 'doing'", [lock]
    )]


class CleanProcrastinateTables:
    """Procrastinate's Django models are unmanaged, so TransactionTestCase's
    flush never touches their tables: rows these tests commit would leak into
    later tests (and a leftover ``todo`` job would be fetched before ours)."""

    def setUp(self):
        super().setUp()
        self._truncate()

    def tearDown(self):
        self._truncate()
        super().tearDown()

    @staticmethod
    def _truncate():
        _sql(
            "TRUNCATE procrastinate_jobs, procrastinate_events, procrastinate_workers, "
            "procrastinate_periodic_defers"
        )


class ProcrastinateHazardTests(CleanProcrastinateTables, TransactionTestCase):
    """Tripwires on the library behavior the fixes exist for. If a Procrastinate
    upgrade makes any of these pass differently, revisit ``app.tasks``."""

    def test_retrying_a_doing_job_collides_with_a_queued_twin(self):
        lock = "deps:hazard-1"
        _insert_job(status="doing", lock=lock)
        doing = _doing_jobs(lock)[0]
        _insert_job(status="todo", lock=lock)

        with self.assertRaises(IntegrityError), transaction.atomic():
            _sql("SELECT procrastinate_retry_job_v1(%s, now(), NULL, NULL, NULL)", [doing])

        # The failed UPDATE leaves the job exactly where it was: a zombie.
        self.assertEqual(_job(doing)["status"], "doing")

    def test_a_doing_job_blocks_its_queued_twin_from_being_fetched(self):
        lock = "deps:hazard-2"
        worker_id = _register_worker()
        doing = _insert_job(status="doing", lock=lock, worker_id=worker_id)
        twin = _insert_job(status="todo", lock=lock)

        self.assertIsNone(_next_fetchable_job_id(worker_id))

        _sql("SELECT procrastinate_finish_job_v1(%s, 'failed', false)", [doing])
        self.assertEqual(_next_fetchable_job_id(worker_id), twin)


class WorkerProcessingTests(CleanProcrastinateTables, TransactionTestCase):
    """Drive Procrastinate's real ``Worker._process_job`` over a failing
    mapping run. Whatever the task does on failure, the job row must never be
    left in ``doing`` while a worker is alive."""

    def setUp(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        self.project = baker.make("app.Project", tenant=tenant, platform_connection=conn)
        self.lock = f"deps:{self.project.id}"
        self.worker_id = _register_worker()

    def _process(self, job_id: int) -> None:
        worker = worker_module.Worker(procrastinate_app, queues=[QUEUE], install_signal_handlers=False)
        job = jobs.Job(
            id=job_id,
            status="doing",
            queue=QUEUE,
            lock=self.lock,
            queueing_lock=self.lock,
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
            abort_reason=lambda: None,
        )
        with patch("app.application.dependency_agent.infer_and_store") as run:
            run.side_effect = RuntimeError("provider said no")
            asyncio.run(worker._process_job(context))

    def test_failed_run_with_queued_twin_leaves_no_zombie_and_frees_the_twin(self):
        doing = _insert_job(
            status="doing", lock=self.lock, worker_id=self.worker_id,
            args='{"project_id": "%s"}' % self.project.id,
        )
        twin = _insert_job(status="todo", lock=self.lock, args='{"project_id": "%s"}' % self.project.id)

        self._process(doing)

        self.assertEqual(_doing_jobs(self.lock), [], "a job was left in 'doing' on a live worker")
        self.assertEqual(_job(twin)["status"], "todo")
        self.assertEqual(_next_fetchable_job_id(self.worker_id), twin)
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, "failed")
        self.assertIn("provider said no", self.project.deps_error)

    def test_failed_run_without_twin_is_scheduled_for_retry(self):
        doing = _insert_job(
            status="doing", lock=self.lock, worker_id=self.worker_id,
            args='{"project_id": "%s"}' % self.project.id,
        )

        self._process(doing)

        row = _job(doing)
        self.assertEqual(row["status"], "todo")
        self.assertIsNotNone(row["scheduled_at"])
        self.assertEqual(row["attempts"], 1)


class RecoverySweepRealDbTests(CleanProcrastinateTables, TransactionTestCase):
    """``recover_stalled_jobs`` against real rows: orphans whose worker is gone."""

    def test_orphan_with_twin_is_failed_and_lonely_orphan_is_requeued(self):
        paired = _insert_job(status="doing", lock="deps:paired")  # worker_id NULL = orphan
        twin = _insert_job(status="todo", lock="deps:paired")
        lonely = _insert_job(status="doing", lock="deps:lonely")

        recovered = asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))

        self.assertEqual(recovered, 2)
        self.assertEqual(_job(paired)["status"], "failed")
        self.assertEqual(_job(twin)["status"], "todo")
        self.assertEqual(_job(lonely)["status"], "todo")
        self.assertEqual(_doing_jobs("deps:paired"), [])
        self.assertEqual(_doing_jobs("deps:lonely"), [])

    def test_job_on_a_live_worker_is_left_alone(self):
        worker_id = _register_worker()
        running = _insert_job(status="doing", lock="deps:live", worker_id=worker_id)

        asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))

        self.assertEqual(_job(running)["status"], "doing")


class RetryingTasksGuardTheirTwinsTests(TransactionTestCase):
    """Structural guard: a task that Procrastinate may retry must refuse the
    retry when a newer job with its queueing_lock is queued. A new task that
    copies ``retry=`` without the guard reintroduces the zombie."""

    def test_every_task_with_a_retry_strategy_checks_for_a_queued_twin(self):
        retrying = [t for t in procrastinate_app.tasks.values() if t.retry_strategy]
        self.assertTrue(retrying, "expected at least one retrying task (infer_project_dependencies)")
        for task in retrying:
            with self.subTest(task=task.name):
                self.assertTrue(
                    task.pass_context,
                    f"{task.name} retries but has no job context to read its queueing_lock from",
                )
                self.assertIn(
                    "_newer_job_queued",
                    inspect.getsource(task.func),
                    f"{task.name} retries without checking for a queued twin",
                )
