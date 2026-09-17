"""Background tasks (Procrastinate, Postgres-backed).

Registered at startup via ``AppConfig.ready`` so the worker
(``manage.py procrastinate worker``) and deferring code both see them.
"""
from __future__ import annotations

import logging
import time

from django.utils import timezone
from procrastinate import exceptions
from procrastinate.contrib.django import app

logger = logging.getLogger(__name__)

# A worker silent for this long is presumed dead; its in-flight jobs are
# reclaimed. Comfortably above the heartbeat interval to avoid false positives.
STALE_WORKER_SECONDS = 90


# A mapping run is attempted this many times inside ONE job before the job
# is failed, with a linear pause between attempts. Retries never leave the
# job: Procrastinate's own ``retry=`` moves the ``doing`` row back to
# ``todo``, and when a coalesced twin already waits in ``todo`` that UPDATE
# violates the one-``todo``-per-queueing_lock index. The library swallows the
# error, the row stays ``doing`` on a live worker forever, and the twin can
# never start because the ``lock`` is still held (a "zombie"). See
# ``tests/application/test_job_zombie_invariants.py``.
INFERENCE_ATTEMPTS = 3
INFERENCE_RETRY_DELAY_SECONDS = 10
_sleep = time.sleep  # seam for tests


@app.task(queue="graph", name="infer_project_dependencies")
def infer_project_dependencies(project_id: str) -> None:
    """Analyze one project's repo and (re)write its dependency edges.

    Idempotent: re-running replaces the project's edges. Deferred with a
    per-project ``queueing_lock`` (coalesce) + ``lock`` (serialize) — see
    ``app.application.subscribers``.

    Failures are retried here, in-process, up to ``INFERENCE_ATTEMPTS`` times.
    No Procrastinate retry strategy is declared on purpose, so the job row
    only ever moves ``doing`` → ``succeeded`` or ``doing`` → ``failed`` and
    never back to ``todo``. After the last attempt the exception is raised so
    Procrastinate records the job as ``failed``; the failure text lives on the
    project (``deps_status`` / ``deps_error``).
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
    for attempt in range(1, INFERENCE_ATTEMPTS + 1):
        try:
            infer_and_store(project)
            return
        except Exception as exc:
            logger.exception(
                "dependency inference failed for project %s (attempt %d/%d)",
                project_id,
                attempt,
                INFERENCE_ATTEMPTS,
            )
            if attempt == INFERENCE_ATTEMPTS:
                Project.objects.filter(pk=project_id).update(
                    deps_status=Project.DepsStatus.FAILED, deps_error=str(exc)[:2000]
                )
                raise  # no retry strategy: Procrastinate marks the job failed
            _sleep(INFERENCE_RETRY_DELAY_SECONDS * attempt)


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
    """Clean up jobs orphaned by a crashed worker; returns how many were handled.

    Procrastinate's worker loop won't rescue another (dead) worker's in-flight
    job — it stays stuck in ``doing`` forever. Workers heartbeat; here we find
    jobs whose worker has gone silent and either put them back to ``todo`` so
    a live worker re-runs them (our tasks are idempotent) or, when a newer job
    with the same queueing_lock is already queued, fail them so that job can
    run. Then prune the dead workers. Async so it runs natively in the
    worker's event loop.
    """
    from procrastinate.jobs import Status

    jm = app.job_manager
    stalled = list(await jm.get_stalled_jobs(seconds_since_heartbeat=STALE_WORKER_SECONDS))
    handled = 0
    for job in stalled:
        try:
            # A newer job for the same work may already be waiting (deferred
            # while this one sat orphaned in ``doing``). Procrastinate allows
            # at most one ``todo`` job per queueing_lock, so requeuing this one
            # would violate that index — and the waiting job can never start
            # while this one holds the ``lock`` in ``doing``. Fail the orphan
            # and let the queued job run instead.
            queued_twins = (
                list(
                    await jm.list_jobs_async(
                        queueing_lock=job.queueing_lock, status=Status.TODO.value
                    )
                )
                if job.queueing_lock
                else []
            )
            if queued_twins:
                logger.warning(
                    "failing stalled job %s (task=%s): a newer job is already queued",
                    job.id,
                    job.task_name,
                )
                await jm.finish_job_by_id_async(job.id, Status.FAILED, delete_job=False)
            else:
                logger.warning("recovering stalled job %s (task=%s)", job.id, job.task_name)
                await jm.retry_job_by_id_async(job.id, retry_at=timezone.now())
            handled += 1
        except exceptions.UniqueViolation:
            # The twin check above raced a twin deferred in between: the
            # requeue hit the one-todo-per-queueing_lock index. Expected and
            # self-healing (the next sweep sees the twin and fails this
            # orphan), so log it without a traceback. Note ``exc_info`` is
            # deliberately off: Procrastinate's Django connector re-raises the
            # driver error with ``raise exc.__cause__``, which makes the
            # exception chain cyclic (psycopg error -> Django IntegrityError
            # -> psycopg error). Stdlib logging copes; rich's traceback
            # renderer, installed on the root logger by FastMCP, loops forever
            # on it and hung the CI test job (PR #113).
            logger.warning(
                "stalled job %s (task=%s) collided with a newly queued twin; "
                "will fail it on the next sweep",
                job.id,
                job.task_name,
            )
        except Exception:
            # One unrecoverable job must not abort the sweep for the others.
            logger.exception("could not recover stalled job %s", job.id)
    await jm.prune_stalled_workers(seconds_since_heartbeat=STALE_WORKER_SECONDS)
    return handled
