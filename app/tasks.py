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


@app.task(queue="standards", name="run_standards")
def run_standards(project_id: str, execution_ids: list[str]) -> None:
    """Run the given standard executions of one project in the sandbox.

    The rows are created RUNNING at enqueue time (see
    ``app.application.standard_runs.enqueue_run``) so the project page can show
    them immediately; this job fills them in. The access token is fetched once
    per job; each execution reads the repository at its own ``ref``.

    Only executions of ``project_id`` are touched: the token and LLM keys in
    the input config belong to that project's workspace, so an id from
    anywhere else is ignored rather than run with them. Idempotent: a row that
    is no longer RUNNING was finished by an earlier attempt and is skipped, so
    a re-run after ``recover_stalled_jobs`` never duplicates work. No
    Procrastinate retry: on failure every remaining row is marked ERROR (a
    retry would find nothing left to do), and rows a dead worker left RUNNING
    are expired by ``expire_stale_standard_runs``.
    """
    # Imported lazily so task registration doesn't pull in Django models at
    # import time (the worker imports this module early).
    from app.application.standard_engine import StandardEngine
    from app.domain.models import Project, StandardExecution

    def _fail(rows, message: str) -> None:
        rows.filter(status=StandardExecution.Status.RUNNING).update(
            status=StandardExecution.Status.ERROR,
            message=message,
            details={"error": message},
        )

    project = (
        Project.objects.select_related("platform_connection")
        .filter(pk=project_id)
        .first()
    )
    if project is None:
        logger.warning("run_standards: project %s no longer exists", project_id)
        _fail(
            StandardExecution.objects.filter(pk__in=execution_ids, project_id=project_id),
            "project no longer exists",
        )
        return

    executions = (
        StandardExecution.objects.filter(pk__in=execution_ids, project=project)
        .select_related("standard", "project")
        .order_by("created_at")
    )
    engine = StandardEngine()
    try:
        input_config = engine.build_input_config(project)
        for execution in executions:
            if execution.status != StandardExecution.Status.RUNNING:
                continue  # already finished by an earlier attempt
            if execution.standard is None:
                # Deleted between enqueue and run — nothing left to execute.
                _fail(
                    StandardExecution.objects.filter(pk=execution.pk),
                    "standard no longer exists",
                )
                continue
            engine.run_execution(execution, input_config)
    except Exception as exc:
        logger.exception("run_standards failed for project %s", project_id)
        _fail(executions, str(exc)[:2000])
        raise


@app.periodic(cron="*/5 * * * *")
@app.task(queue="standards", name="expire_stale_standard_runs", pass_context=False)
def expire_stale_standard_runs(timestamp: int) -> int:
    """Turn RUNNING executions nobody will finish into ERROR rows.

    A worker that dies mid-run, a job lost before any worker saw it, or rows
    from before runs went to the background all leave executions RUNNING with
    no one to finish them — and a RUNNING row blocks re-running that standard
    and keeps the project page polling. See ``standard_runs.expire_stale_runs``.
    """
    from app.application.standard_runs import expire_stale_runs

    return expire_stale_runs()


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
