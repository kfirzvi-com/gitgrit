import asyncio
from unittest.mock import AsyncMock, MagicMock

from django.test import SimpleTestCase

from app import tasks
from tests.support import MonkeyPatchMixin


class RecoverStalledJobsTests(MonkeyPatchMixin, SimpleTestCase):
    def _job_manager(self, stalled, queued=()):
        jm = MagicMock()
        jm.get_stalled_jobs = AsyncMock(return_value=stalled)
        jm.list_jobs_async = AsyncMock(return_value=list(queued))
        jm.retry_job_by_id_async = AsyncMock()
        jm.finish_job_by_id_async = AsyncMock()
        jm.prune_stalled_workers = AsyncMock(return_value=[])
        self.monkeypatch.setattr(tasks.app, "job_manager", jm, raising=False)
        return jm

    def test_requeues_each(self):
        j1 = MagicMock(id=1, task_name="infer_project_dependencies", queueing_lock="deps:a")
        j2 = MagicMock(id=2, task_name="infer_project_dependencies", queueing_lock="deps:b")
        jm = self._job_manager([j1, j2])

        recovered = asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))

        self.assertEqual(recovered, 2)
        self.assertEqual(jm.retry_job_by_id_async.await_count, 2)
        jm.prune_stalled_workers.assert_awaited_once()

    def test_noop_when_none(self):
        jm = self._job_manager([])

        recovered = asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))

        self.assertEqual(recovered, 0)
        jm.retry_job_by_id_async.assert_not_awaited()

    def test_fails_orphan_when_a_newer_job_is_already_queued(self):
        """Regression: an orphaned ``doing`` job whose queueing_lock already has
        a ``todo`` twin. Requeuing it collides with Procrastinate's one-todo-
        per-queueing_lock index, so the sweep used to raise every run and the
        twin could never start (the orphan still held the ``lock``)."""
        orphan = MagicMock(id=1, task_name="infer_project_dependencies", queueing_lock="deps:p")
        twin = MagicMock(id=2, status="todo", queueing_lock="deps:p")
        jm = self._job_manager([orphan], queued=[twin])

        recovered = asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))

        self.assertEqual(recovered, 1)
        jm.retry_job_by_id_async.assert_not_awaited()
        jm.finish_job_by_id_async.assert_awaited_once()
        args, kwargs = jm.finish_job_by_id_async.await_args
        self.assertEqual(args[0], 1)
        self.assertEqual(args[1].value, "failed")
        self.assertFalse(kwargs["delete_job"])

    def test_one_failure_does_not_abort_the_sweep(self):
        j1 = MagicMock(id=1, task_name="infer_project_dependencies", queueing_lock=None)
        j2 = MagicMock(id=2, task_name="infer_project_dependencies", queueing_lock=None)
        jm = self._job_manager([j1, j2])
        jm.retry_job_by_id_async = AsyncMock(side_effect=[RuntimeError("boom"), None])

        recovered = asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))

        self.assertEqual(recovered, 1)
        self.assertEqual(jm.retry_job_by_id_async.await_count, 2)
        jm.prune_stalled_workers.assert_awaited_once()
