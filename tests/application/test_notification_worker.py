"""notify() from inside a running sync task, end to end on the REAL worker code.

Sources will call notify() from inside background jobs (a failed standard
run, a failed graph run). Those jobs are sync functions the worker runs on
another thread via ``sync_to_async``; this checks a defer from there lands a
``deliver_notification`` job on the ``notifications`` queue, and that the
worker then runs it into inbox rows.

TransactionTestCase for the same reason as ``test_job_zombie_invariants``:
Procrastinate's Django connector queries from another thread, which cannot
see an uncommitted test transaction.
"""
from __future__ import annotations

import asyncio
import json
import time

from django.test import TransactionTestCase
from model_bakery import baker
from procrastinate import jobs
from procrastinate import worker as worker_module
from procrastinate.contrib.django import app as procrastinate_app
from procrastinate.job_context import JobContext

from app.application.notifications import notify
from app.domain.models import NotificationDelivery
from app.domain.notifications import Notice, Severity
from tests.application.test_job_zombie_invariants import CleanProcrastinateTables, _sql

SOURCE_TASK = "test_notification_source"
SOURCE_QUEUE = "test_notification_source"


def _jobs(queue: str) -> list[dict]:
    rows = _sql(
        "SELECT id, task_name, args, status FROM procrastinate_jobs "
        "WHERE queue_name = %s ORDER BY id",
        [queue],
    )
    return [dict(zip(("id", "task_name", "args", "status"), r)) for r in rows]


def _process(row: dict, queue: str) -> None:
    """Run one queued job through Procrastinate's own ``Worker._process_job``."""
    _sql("UPDATE procrastinate_jobs SET status = 'doing' WHERE id = %s", [row["id"]])
    args = row["args"] if isinstance(row["args"], dict) else json.loads(row["args"])
    worker = worker_module.Worker(
        procrastinate_app, queues=[queue], install_signal_handlers=False
    )
    job = jobs.Job(
        id=row["id"],
        status="doing",
        queue=queue,
        lock=None,
        queueing_lock=None,
        task_name=row["task_name"],
        task_kwargs=args,
        attempts=0,
    )
    context = JobContext(
        app=procrastinate_app,
        worker_name="test-worker",
        worker_queues=[queue],
        job=job,
        start_timestamp=time.time(),
        abort_reason=lambda: None,
    )
    asyncio.run(worker._process_job(context))


class NotifyFromRunningTaskTests(CleanProcrastinateTables, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.tenant = baker.make("app.Tenant")
        self.admin = baker.make("app.User")
        baker.make("app.Membership", user=self.admin, tenant=self.tenant, role="admin")

        def source(tenant_id: str) -> None:
            notify(
                Notice(
                    kind="run.failed",
                    tenant_id=tenant_id,
                    severity=Severity.CRITICAL,
                    title="Run failed",
                    body="",
                    url="/x",
                )
            )

        # A stand-in source job, registered for this test only so it never
        # leaks into the app's task list (which other tests iterate).
        self.source = procrastinate_app.task(name=SOURCE_TASK, queue=SOURCE_QUEUE)(source)
        self.addCleanup(procrastinate_app.tasks.pop, SOURCE_TASK, None)

    def test_notify_inside_a_sync_task_defers_a_delivery_job_that_runs(self):
        self.source.defer(tenant_id=str(self.tenant.pk))
        [source_job] = _jobs(SOURCE_QUEUE)

        _process(source_job, SOURCE_QUEUE)

        self.assertEqual(_jobs(SOURCE_QUEUE)[0]["status"], "succeeded")
        [delivery_job] = _jobs("notifications")
        self.assertEqual(delivery_job["task_name"], "deliver_notification")
        self.assertEqual(delivery_job["status"], "todo")

        _process(delivery_job, "notifications")

        self.assertEqual(_jobs("notifications")[0]["status"], "succeeded")
        row = NotificationDelivery.objects.get(channel="inbox")
        self.assertEqual(row.recipient_id, self.admin.pk)
        self.assertEqual(row.status, "sent")
