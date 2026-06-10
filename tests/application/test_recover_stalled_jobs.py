import asyncio
from unittest.mock import AsyncMock, MagicMock

from app import tasks


def test_recover_stalled_jobs_requeues_each(monkeypatch):
    j1 = MagicMock(id=1, task_name="infer_project_dependencies")
    j2 = MagicMock(id=2, task_name="infer_project_dependencies")
    jm = MagicMock()
    jm.get_stalled_jobs = AsyncMock(return_value=[j1, j2])
    jm.retry_job_by_id_async = AsyncMock()
    jm.prune_stalled_workers = AsyncMock(return_value=[])
    monkeypatch.setattr(tasks.app, "job_manager", jm, raising=False)

    recovered = asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))

    assert recovered == 2
    assert jm.retry_job_by_id_async.await_count == 2
    jm.prune_stalled_workers.assert_awaited_once()


def test_recover_stalled_jobs_noop_when_none(monkeypatch):
    jm = MagicMock()
    jm.get_stalled_jobs = AsyncMock(return_value=[])
    jm.retry_job_by_id_async = AsyncMock()
    jm.prune_stalled_workers = AsyncMock(return_value=[])
    monkeypatch.setattr(tasks.app, "job_manager", jm, raising=False)

    recovered = asyncio.run(tasks.recover_stalled_jobs.func(timestamp=0))

    assert recovered == 0
    jm.retry_job_by_id_async.assert_not_awaited()
