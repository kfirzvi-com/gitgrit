"""Background tasks (Procrastinate, Postgres-backed).

Registered at startup via ``AppConfig.ready`` so the worker
(``manage.py procrastinate worker``) and deferring code both see them.
"""
from __future__ import annotations

import functools
import logging
import time

from django.db import connections
from django.utils import timezone
from procrastinate import exceptions
from procrastinate.contrib.django import app

logger = logging.getLogger(__name__)

# A worker silent for this long is presumed dead; its in-flight jobs are
# reclaimed. This is Procrastinate's database heartbeat (default every 10s),
# not the CloudWatch liveness line (app/worker_heartbeat.py). Comfortably
# above that database interval to avoid false positives.
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


# Sync tasks run on a pool of reused worker threads, and Django keeps one DB
# connection per thread. Outside a request nothing ever retires those
# connections, so once Postgres drops one (restart, failover, idle kill) the
# thread holding it fails every job it picks up with "the connection is
# closed" — before the task can mark its rows ERROR. Do what Django does at
# the start and end of every request: drop connections that are unusable or
# past CONN_MAX_AGE (with the default 0, that is every connection), so each
# job starts on a fresh one and an idle thread holds none.


def _close_old_connections() -> None:
    # Like ``django.db.close_old_connections``, but never under an open
    # transaction: closing there would break it (only tests run tasks so).
    for conn in connections.all(initialized_only=True):
        if not conn.in_atomic_block:
            conn.close_if_unusable_or_obsolete()


def fresh_db_connection(func):
    """Run a sync task between two connection sweeps (see above)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        _close_old_connections()
        try:
            return func(*args, **kwargs)
        finally:
            _close_old_connections()

    return wrapper


@app.task(queue="graph", name="infer_project_dependencies")
@fresh_db_connection
def infer_project_dependencies(project_id: str) -> None:
    """Analyze one project's repo and (re)write its dependency edges.

    Idempotent: re-running replaces the project's edges. Deferred with a
    per-project ``queueing_lock`` (coalesce) + ``lock`` (serialize) — see
    ``app.application.subscribers``.

    Unexpected failures are retried here, in-process, up to
    ``INFERENCE_ATTEMPTS`` times. No Procrastinate retry strategy is declared
    on purpose, so the job row only ever moves ``doing`` → ``succeeded`` or
    ``doing`` → ``failed`` and never back to ``todo``. After the last attempt
    the exception is raised so Procrastinate records the job as ``failed``;
    the failure text lives on the project (``deps_status`` / ``deps_error``).

    A workspace that cannot run inference — no reasoning model, or that
    model's AI budget is missing or used up — raises
    ``DependencyInferenceUnavailable``. Retrying would fail the same way, so
    the failure is recorded on the project, logged at warning, and the job
    returns. Procrastinate records it ``succeeded``, and the worker logs
    "ended with status: Success".
    """
    # Imported lazily so task registration doesn't pull in Django models at
    # import time (the worker imports this module early).
    from app.application.dependency_agent import (
        DependencyInferenceUnavailable,
        infer_and_store,
    )
    from app.application.event_bus import publish
    from app.domain.events import DependencyInferenceFailed
    from app.domain.models import Project

    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        logger.warning("infer_project_dependencies: project %s no longer exists", project_id)
        return

    # Read before this run: only a successful refresh sets deps_analyzed_at.
    had_worked_before = project.deps_analyzed_at is not None
    Project.objects.filter(pk=project_id).update(
        deps_status=Project.DepsStatus.RUNNING, deps_error=""
    )

    def _record_failure(exc: BaseException) -> None:
        message = str(exc)[:2000]
        Project.objects.filter(pk=project_id).update(
            deps_status=Project.DepsStatus.FAILED, deps_error=message
        )
        publish(
            DependencyInferenceFailed(
                project_id=str(project.pk),
                tenant_id=str(project.tenant_id),
                error=message,
                had_worked_before=had_worked_before,
                provider_status=getattr(exc, "status_code", None),
            )
        )

    for attempt in range(1, INFERENCE_ATTEMPTS + 1):
        try:
            infer_and_store(project)
            return
        except DependencyInferenceUnavailable as exc:
            # Expected until someone configures a model or raises the budget.
            # One attempt, no pause, and no re-raise: the job is not an error.
            logger.warning(
                "dependency inference unavailable for project %s: %s",
                project_id,
                exc,
            )
            _record_failure(exc)
            return
        except Exception as exc:
            logger.exception(
                "dependency inference failed for project %s (attempt %d/%d)",
                project_id,
                attempt,
                INFERENCE_ATTEMPTS,
            )
            if attempt == INFERENCE_ATTEMPTS:
                _record_failure(exc)
                raise  # no retry strategy: Procrastinate marks the job failed
            _sleep(INFERENCE_RETRY_DELAY_SECONDS * attempt)


@app.task(queue="standards", name="run_standards")
@fresh_db_connection
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
    from app.application.commit_checks import pin_head_commits
    from app.application.event_bus import publish
    from app.application.scoring import score_checks
    from app.application.standard_engine import StandardEngine
    from app.domain.events import StandardRunFinished
    from app.domain.models import Project, StandardExecution

    def _fail(rows, message: str) -> None:
        rows.filter(status=StandardExecution.Status.RUNNING).update(
            status=StandardExecution.Status.ERROR,
            message=message,
            details={"error": message},
        )

    def _publish_finished(error: str = "") -> None:
        """Score the commits whose checks this run finished, then tell
        listeners how the run ended. Outcomes are re-read from the database
        and only this project's rows count."""
        score_checks(
            set(
                StandardExecution.objects.filter(pk__in=execution_ids, project=project)
                .exclude(commit_check=None)
                .values_list("commit_check_id", flat=True)
            )
        )
        rows = list(
            StandardExecution.objects.filter(pk__in=execution_ids, project=project)
            .order_by("created_at")
            .values_list("pk", "status")
        )
        statuses = [status for _, status in rows]
        publish(
            StandardRunFinished(
                project_id=str(project.pk),
                tenant_id=str(project.tenant_id),
                execution_ids=tuple(str(pk) for pk, _ in rows),
                passed=statuses.count(StandardExecution.Status.PASSED),
                failed=statuses.count(StandardExecution.Status.FAILED),
                errored=statuses.count(StandardExecution.Status.ERROR),
                error=error,
            )
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
        .select_related("standard", "project", "commit_check", "standard_version")
        .order_by("created_at")
    )
    engine = StandardEngine()
    try:
        pin_head_commits(project, executions)
        input_config = engine.build_input_config(project)
        for execution in executions:
            if execution.status != StandardExecution.Status.RUNNING:
                continue  # already finished by an earlier attempt
            if execution.standard is None or execution.standard.archived_at:
                # Deleted between enqueue and run — nothing left to execute.
                _fail(
                    StandardExecution.objects.filter(pk=execution.pk),
                    "standard no longer exists",
                )
                continue
            engine.run_execution(execution, input_config)
    except Exception as exc:
        logger.exception("run_standards failed for project %s", project_id)
        message = str(exc)[:2000]
        _fail(executions, message)
        _publish_finished(error=message)
        raise
    finally:
        engine.close()
    _publish_finished()


# The one worker serves every queue and takes jobs by priority, then age, so
# without this a notification waits behind every standard run queued before it.
NOTIFICATION_PRIORITY = 10


@app.task(
    queue="notifications", name="deliver_notification", priority=NOTIFICATION_PRIORITY
)
def deliver_notification(notification_id: str) -> None:
    """Deliver one stored notification on its channels. Runs ahead of queued
    standard runs and graph jobs (see ``NOTIFICATION_PRIORITY``).

    No Procrastinate retry: a channel that fails gets a FAILED ``DeliveryLog``
    row, which is the record; nothing re-sends it. ``dispatch`` skips channels
    that already have a SENT row, so a re-run after a crashed worker
    (``recover_stalled_jobs``) never double-posts.
    """
    from app.application.notifications.dispatcher import dispatch

    dispatch(notification_id)


@app.task(
    queue="notifications",
    name="send_email",
    priority=NOTIFICATION_PRIORITY,
)
def send_email(template: str, to: list[str], context: dict) -> None:
    """Render and send one templated email (see ``app.infrastructure.mailer``).
    Off the request so a slow or failing mail server never holds up the page
    that triggered it. No Procrastinate retry (see the note on
    ``INFERENCE_ATTEMPTS``): a failed send leaves a failed job, which is the
    record."""
    from app.infrastructure.mailer import send_templated

    send_templated(template, to, context)


@app.periodic(cron="*/5 * * * *")
@app.task(queue="standards", name="expire_stale_standard_runs", pass_context=False)
@fresh_db_connection
def expire_stale_standard_runs(timestamp: int) -> int:
    """Turn RUNNING executions nobody will finish into ERROR rows.

    A worker that dies mid-run, a job lost before any worker saw it, or rows
    from before runs went to the background all leave executions RUNNING with
    no one to finish them — and a RUNNING row blocks re-running that standard
    and keeps the project page polling. See ``standard_runs.expire_stale_runs``.

    Its success line also matches the CloudWatch WorkerHeartbeat filter, which
    is how liveness used to be measured. The job waits on the single worker
    slot, so a long standard run delays that line. Liveness is now the thread
    in ``app.worker_heartbeat``; this job stays because it is the sweep.
    """
    from app.application.standard_runs import expire_stale_runs

    return expire_stale_runs()


@app.periodic(cron="* * * * *")
@app.task(queue="standards", name="run_scheduled_standards", pass_context=False)
@fresh_db_connection
def run_scheduled_standards(timestamp: int) -> int:
    """Queue the attached standards whose schedule is due
    (``app.application.schedules.StandardScheduler``). Every minute: a
    schedule's finest grain."""
    from app.application.schedules import StandardScheduler

    return StandardScheduler().run_due()


@app.periodic(cron="17 * * * *")
@app.task(queue="graph", name="snapshot_workspace_usage", pass_context=False)
@fresh_db_connection
def snapshot_workspace_usage(timestamp: int) -> int:
    """Note every workspace's project count for today (``UsageMeter``), so
    days with no runs still count the projects held. Hourly rather than
    daily: idempotent, and a worker down at midnight misses no day."""
    from app.application.usage import UsageMeter

    return UsageMeter.snapshot_all()


@app.task(queue="graph", name="sync_delivery")
@fresh_db_connection
def sync_delivery(project_id: str) -> None:
    """Sync one project's delivery data (DORA metrics) from its Git
    platform. Idempotent; a source that can't be read is noted on the
    project's delivery settings rather than failing the job."""
    from app.application.delivery import DeliverySync
    from app.infrastructure.delivery import deployment_sources_for, repository_activity_for
    from app.models import Project

    project = Project.objects.filter(pk=project_id).select_related("platform_connection").first()
    if project is None:
        return
    DeliverySync(deployment_sources_for, repository_activity_for).run(project)


@app.periodic(cron="* * * * *")
@app.task(queue="graph", name="sync_due_deliveries", pass_context=False)
@fresh_db_connection
def sync_due_deliveries(timestamp: int) -> int:
    """Ask for a sync of every Git project due one (every
    ``GITGRIT_DELIVERY_SYNC_MINUTES``), so pages never have to read the
    platform themselves."""
    from django.utils import timezone

    from app.application.delivery import DeliverySyncRequest, DeliverySyncSchedule

    due = list(DeliverySyncSchedule.due(timezone.now()))
    for project in due:
        DeliverySyncRequest.send(project)
    return len(due)


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
            # renderer (FastMCP used to install it on the root logger) loops forever
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
