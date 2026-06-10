"""Background tasks (Procrastinate, Postgres-backed).

Registered at startup via ``AppConfig.ready`` so the worker
(``manage.py procrastinate worker``) and deferring code both see them.
"""
from __future__ import annotations

import logging

from django.utils import timezone
from procrastinate.contrib.django import app

logger = logging.getLogger(__name__)

# A worker silent for this long is presumed dead; its in-flight jobs are
# reclaimed. Comfortably above the heartbeat interval to avoid false positives.
STALE_WORKER_SECONDS = 90


@app.task(queue="graph", name="infer_project_dependencies", retry=2)
def infer_project_dependencies(project_id: str) -> None:
    """Analyze one project's repo and (re)write its dependency edges.

    Idempotent: re-running replaces the project's edges. Deferred with a
    per-project ``queueing_lock`` (coalesce) + ``lock`` (serialize) — see
    ``app.application.subscribers``.
    """
    # Imported lazily so task registration doesn't pull in Django models at
    # import time (the worker imports this module early).
    from app.application.dependency_agent import infer_and_store
    from app.domain.models import Project

    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        logger.warning("infer_project_dependencies: project %s no longer exists", project_id)
        return

    Project.objects.filter(pk=project_id).update(
        deps_status=Project.DepsStatus.RUNNING, deps_error=""
    )
    try:
        infer_and_store(project)
    except Exception as exc:
        logger.exception("dependency inference failed for project %s", project_id)
        Project.objects.filter(pk=project_id).update(
            deps_status=Project.DepsStatus.FAILED, deps_error=str(exc)[:2000]
        )
        raise  # surface to Procrastinate so it can retry


@app.periodic(cron="*/2 * * * *")
@app.task(queue="graph", name="recover_stalled_jobs", pass_context=False)
async def recover_stalled_jobs(timestamp: int) -> int:
    """Requeue jobs orphaned by a crashed worker.

    Procrastinate's worker loop won't rescue another (dead) worker's in-flight
    job — it stays stuck in ``doing`` forever. Workers heartbeat; here we find
    jobs whose worker has gone silent, put them back to ``todo`` so a live
    worker re-runs them (our tasks are idempotent), then prune the dead workers.
    Async so it runs natively in the worker's event loop.
    """
    jm = app.job_manager
    stalled = list(await jm.get_stalled_jobs(seconds_since_heartbeat=STALE_WORKER_SECONDS))
    for job in stalled:
        logger.warning("recovering stalled job %s (task=%s)", job.id, job.task_name)
        await jm.retry_job_by_id_async(job.id, retry_at=timezone.now())
    await jm.prune_stalled_workers(seconds_since_heartbeat=STALE_WORKER_SECONDS)
    return len(stalled)
