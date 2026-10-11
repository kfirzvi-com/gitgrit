"""Sync tasks survive a DB connection Postgres has dropped.

Procrastinate runs sync tasks on reused pool threads, each holding its own
Django connection. Regression: once the server dropped those connections, every
job a thread picked up failed on its first query with "the connection is
closed" — before ``run_standards`` could mark its rows ERROR, so they sat
RUNNING until the stale sweep (itself a sync task, failing the same way).

These run the task on a single-thread pool, like a worker thread being reused,
and drop that thread's connection the way a server-side close looks to Django:
it still holds the handle, but the socket is gone.
"""
from concurrent.futures import ThreadPoolExecutor

from django.db import connection, connections
from django.test import TransactionTestCase
from model_bakery import baker

from app import tasks
from app.domain.models import StandardExecution
from tests.application.test_standard_runs import PASSED, _mocked_runner


def _drop_connection():
    connection.ensure_connection()
    connection.connection.close()


def _holds_connection():
    return connection.connection is not None


class WorkerDbConnectionTests(TransactionTestCase):
    def setUp(self):
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(self.pool.shutdown)
        self.addCleanup(lambda: self.pool.submit(connections.close_all).result())
        tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=tenant)
        standard = baker.make("app.Standard", tenant=tenant, code="A")
        self.execution = baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            event_type="push",
            status=StandardExecution.Status.RUNNING,
        )

    def _on_worker_thread(self, fn, *args, **kwargs):
        return self.pool.submit(fn, *args, **kwargs).result()

    def _run_standards(self):
        tasks.run_standards.func(
            project_id=str(self.project.pk),
            execution_ids=[str(self.execution.pk)],
        )

    def test_run_standards_runs_on_a_thread_whose_connection_was_dropped(self):
        self._on_worker_thread(_drop_connection)

        with _mocked_runner([PASSED]):
            self._on_worker_thread(self._run_standards)

        self.execution.refresh_from_db()
        self.assertEqual(self.execution.status, StandardExecution.Status.PASSED)

    def test_stale_sweep_runs_on_a_thread_whose_connection_was_dropped(self):
        self._on_worker_thread(_drop_connection)

        expired = self._on_worker_thread(
            tasks.expire_stale_standard_runs.func, timestamp=0
        )

        self.assertEqual(expired, 0)

    def test_worker_thread_holds_no_connection_between_jobs(self):
        with _mocked_runner([PASSED]):
            self._on_worker_thread(self._run_standards)

        self.assertFalse(self._on_worker_thread(_holds_connection))
