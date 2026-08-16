import asyncio
from unittest.mock import AsyncMock, MagicMock

from django.test import SimpleTestCase

from app import tasks
from tests.support import MonkeyPatchMixin


class RecoverStalledJobsTests(MonkeyPatchMixin, SimpleTestCase):
    def _job_manager(self, stalled):
        jm = MagicMock()
        jm.get_stalled_jobs = AsyncMock(return_value=stalled)
        jm.retry_job_by_id_async = AsyncMock()
        jm.prune_stalled_workers = AsyncMock(return_value=[])
        self.monkeypatch.setattr(tasks.app, "job_manager", jm, raising=False)
        return jm

    def test_requeues_each(self):
        j1 = MagicMock(id=1, task_name="infer_project_dependencies")
        j2 = MagicMock(id=2, task_name="infer_project_dependencies")
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
