"""Map-worker trigger and coalescing scenarios, on the REAL Procrastinate schema.

Every way a dependency-map run can be started (domain events, the management
command) is exercised here against the actual job tables and, where it
matters, Procrastinate's own worker code. The invariants under test are the
ones whose violation once produced "zombie" jobs:

* after processing, no ``infer_project_dependencies`` row is left in ``doing``;
* at most one ``todo`` row per queueing_lock (rapid triggers coalesce);
* a ``doing`` row never goes back to ``todo`` (no ``deferred_for_retry`` event);
* ``deps_status`` ends terminal, or is ``pending`` only while a ``todo`` waits.

See ``tests/application/test_job_zombie_invariants.py`` for the helpers and the
history.
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

from django.core.management import call_command
from django.db import transaction
from django.test import TransactionTestCase
from model_bakery import baker
from procrastinate import jobs
from procrastinate import worker as worker_module
from procrastinate.contrib.django import app as procrastinate_app
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.job_context import JobContext

from app.application import subscribers
from app.application.event_bus import publish
from app.domain.events import ComponentAddedToStack, ProjectCreated, RepositoryPushed
from app.domain.models import Project
from tests.application.test_job_zombie_invariants import (
    QUEUE,
    TASK,
    CleanProcrastinateTables,
    _doing_jobs,
    _job,
    _next_fetchable_job_id,
    _register_worker,
    _sql,
)

INFER = "app.application.dependency_agent.infer_and_store"
SLEEP = "app.tasks._sleep"


def _map_jobs(where: str = "TRUE", params=()) -> list[dict]:
    rows = _sql(
        "SELECT id, status, lock, queueing_lock, args FROM procrastinate_jobs "
        f"WHERE task_name = %s AND ({where}) ORDER BY id",
        [TASK, *params],
    )
    out = []
    for r in rows:
        row = dict(zip(("id", "status", "lock", "queueing_lock", "args"), r))
        # Django registers a no-op jsonb loader on its connections.
        row["args"] = json.loads(row["args"]) if isinstance(row["args"], str) else row["args"]
        out.append(row)
    return out


def _todo_count(queueing_lock: str) -> int:
    return _sql(
        "SELECT count(*) FROM procrastinate_jobs WHERE queueing_lock = %s AND status = 'todo'",
        [queueing_lock],
    )[0][0]


def _retry_events() -> list[int]:
    """Job ids that ever moved ``doing`` -> ``todo``. Must always be empty."""
    return [
        r[0]
        for r in _sql(
            "SELECT e.job_id FROM procrastinate_events e JOIN procrastinate_jobs j "
            "ON j.id = e.job_id WHERE j.task_name = %s AND e.type = 'deferred_for_retry'",
            [TASK],
        )
    ]


def _ok(project: Project) -> None:
    """Stand-in for a successful ``infer_and_store``: the real one flips the
    project to OK itself, so the stub must too for the status invariant."""
    Project.objects.filter(pk=project.pk).update(deps_status=Project.DepsStatus.OK, deps_error="")


def _boom(project: Project) -> None:
    raise RuntimeError("provider said no")


class _Scenario(CleanProcrastinateTables, TransactionTestCase):
    def setUp(self):
        super().setUp()
        subscribers.register()  # idempotent; a test elsewhere may have cleared the bus
        self.tenant = baker.make("app.Tenant")
        self.conn = baker.make("app.PlatformConnection", tenant=self.tenant, platform="github")
        self.project = self._project()
        self.lock = f"deps:{self.project.id}"

    def _project(self) -> Project:
        return baker.make("app.Project", tenant=self.tenant, platform_connection=self.conn)

    def _event(self, cls=RepositoryPushed, project=None, **extra):
        project = project or self.project
        return cls(project_id=str(project.id), tenant_id=str(self.tenant.id), **extra)

    def _stack_event(self, project, stack):
        """What ``stack_service.add_component_to_stack`` publishes for the
        project's root component."""
        return ComponentAddedToStack(
            component_id=str(project.root_component.id),
            project_id=str(project.id),
            stack_id=str(stack.id),
            tenant_id=str(self.tenant.id),
        )

    def _doing_job(self, project=None) -> tuple[int, int]:
        """A row that a live worker is executing right now, with the locks the
        subscriber really uses: ``project:<id>`` to serialize, ``deps:<id>``
        to coalesce."""
        project = project or self.project
        worker_id = _register_worker()
        job_id = _sql(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, queueing_lock, "
            "args, status, worker_id) VALUES (%s, %s, %s, %s, %s::jsonb, 'doing', %s) RETURNING id",
            [
                QUEUE,
                TASK,
                f"project:{project.id}",
                f"deps:{project.id}",
                json.dumps({"project_id": str(project.id)}),
                worker_id,
            ],
        )[0][0]
        return job_id, worker_id

    def _process(self, job_id: int, worker_id: int, project=None, infer=_ok) -> None:
        """Drive Procrastinate's real ``_process_job`` over ``job_id``."""
        project = project or self.project
        worker = worker_module.Worker(
            procrastinate_app, queues=[QUEUE], install_signal_handlers=False, wait=False
        )
        worker.worker_id = worker_id
        job = jobs.Job(
            id=job_id,
            status="doing",
            queue=QUEUE,
            lock=f"project:{project.id}",
            queueing_lock=f"deps:{project.id}",
            task_name=TASK,
            task_kwargs={"project_id": str(project.id)},
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
        with patch(INFER, side_effect=infer), patch(SLEEP):
            asyncio.run(worker._process_job(context))

    def _drain(self, infer=_ok) -> None:
        """Run Procrastinate's real worker loop until the queue is empty, the
        way ``manage.py procrastinate worker`` does: on the worker connector
        (a psycopg pool), not the Django connector, whose rows come back with
        undecoded jsonb and which cannot LISTEN."""
        worker_connector = procrastinate_app.connector.get_worker_connector()

        async def run():
            async with procrastinate_app.open_async():
                await procrastinate_app.run_worker_async(
                    queues=[QUEUE],
                    wait=False,
                    install_signal_handlers=False,
                    listen_notify=False,
                )

        with (
            procrastinate_app.replace_connector(worker_connector),
            patch(INFER, side_effect=infer),
            patch(SLEEP),
        ):
            asyncio.run(run())

    def _assert_settled(self, *projects: Project) -> None:
        """The invariants that hold once the worker has nothing left to do."""
        self.assertEqual(_map_jobs("status IN ('doing', 'todo')"), [], "unfinished map jobs")
        self.assertEqual(_retry_events(), [], "a doing job went back to todo")
        for project in projects:
            project.refresh_from_db()
            self.assertIn(
                project.deps_status,
                {Project.DepsStatus.OK, Project.DepsStatus.FAILED},
                f"{project.name}: deps_status {project.deps_status!r} is not terminal",
            )


class TriggerScenarios(_Scenario):
    def test_1_project_created_queues_exactly_one_job(self):
        publish(self._event(ProjectCreated))

        rows = _map_jobs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "todo")
        self.assertEqual(rows[0]["lock"], f"project:{self.project.id}")
        self.assertEqual(rows[0]["queueing_lock"], self.lock)
        self.assertEqual(rows[0]["args"], {"project_id": str(self.project.id)})
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.PENDING)

    def test_2_two_pushes_with_no_worker_coalesce_and_do_not_poison_the_transaction(self):
        with transaction.atomic():
            publish(self._event(ref="refs/heads/main"))
            publish(self._event(ref="refs/heads/main"))
            # A write after the swallowed unique violation must still land:
            # the defer runs in a savepoint, so the outer transaction is intact.
            Project.objects.filter(pk=self.project.pk).update(name="renamed-after-events")

        self.assertEqual(_todo_count(self.lock), 1)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "renamed-after-events")
        self.assertEqual(self.project.deps_status, Project.DepsStatus.PENDING)

    def test_3_event_during_a_running_job_queues_a_twin_that_runs_after_success(self):
        doing, worker_id = self._doing_job()

        publish(self._event())  # arrives mid-run: allowed, coalesces into ONE todo
        twin = _map_jobs("status = 'todo'")
        self.assertEqual(len(twin), 1)
        self.assertIsNone(_next_fetchable_job_id(worker_id), "twin fetchable while lock is held")

        self._process(doing, worker_id, infer=_ok)

        self.assertEqual(_job(doing)["status"], "succeeded")
        self.assertEqual(_doing_jobs(self.lock), [])
        self.assertEqual(_next_fetchable_job_id(worker_id), twin[0]["id"])

        self._drain(infer=_ok)

        self.assertEqual(_job(twin[0]["id"])["status"], "succeeded")
        self._assert_settled(self.project)

    def test_4_event_during_a_running_job_that_fails_every_attempt(self):
        doing, worker_id = self._doing_job()
        publish(self._event())
        twin = _map_jobs("status = 'todo'")[0]["id"]

        self._process(doing, worker_id, infer=_boom)

        row = _job(doing)
        self.assertEqual(row["status"], "failed", "failed run must end failed, never todo")
        self.assertEqual(_retry_events(), [])
        self.assertEqual(_next_fetchable_job_id(worker_id), twin)
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.FAILED)
        self.assertIn("provider said no", self.project.deps_error)

        self._drain(infer=_ok)

        self.assertEqual(_job(twin)["status"], "succeeded")
        self._assert_settled(self.project)

    def test_5_stack_event_and_management_command_coalesce_to_one_todo(self):
        stack = baker.make("app.Stack", tenant=self.tenant)

        # Command first, then event: the subscriber swallows AlreadyEnqueued.
        call_command("refresh_project_deps", str(self.project.id), verbosity=0)
        publish(self._stack_event(self.project, stack))
        self.assertEqual(_todo_count(self.lock), 1)

        # Event first, then command: same single row. The command does not
        # catch AlreadyEnqueued itself (see report) but the queue stays sane.
        other = self._project()
        publish(self._stack_event(other, stack))
        with self.assertRaises(AlreadyEnqueued):
            call_command("refresh_project_deps", str(other.id), verbosity=0)
        self.assertEqual(_todo_count(f"deps:{other.id}"), 1)

        self.assertEqual(len(_map_jobs()), 2)

    def test_6_management_command_sync_runs_inline_without_job_rows(self):
        with patch(INFER, side_effect=_boom), patch(SLEEP):
            call_command("refresh_project_deps", str(self.project.id), "--sync", verbosity=0)

        self.assertEqual(_map_jobs(), [], "--sync must not enqueue")
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.FAILED)
        self.assertIn("provider said no", self.project.deps_error)

        class _Result:
            internal = external_providers = external_consumers = ()

        def ok_result(project):
            _ok(project)
            return _Result()

        with patch(INFER, side_effect=ok_result), patch(SLEEP):
            call_command("refresh_project_deps", str(self.project.id), "--sync", verbosity=0)

        self.assertEqual(_map_jobs(), [])
        self.project.refresh_from_db()
        self.assertEqual(self.project.deps_status, Project.DepsStatus.OK)
        self.assertEqual(self.project.deps_error, "")

    def test_7_burst_of_events_during_a_running_job_yields_one_todo(self):
        doing, worker_id = self._doing_job()

        for _ in range(10):
            publish(self._event())

        self.assertEqual(_todo_count(self.lock), 1)
        self.assertEqual(_doing_jobs(self.lock), [doing])

        self._process(doing, worker_id, infer=_ok)
        self._drain(infer=_ok)

        self.assertEqual(len(_map_jobs()), 2)
        self._assert_settled(self.project)

    def test_8_real_worker_loop_end_to_end_with_a_mid_run_twin(self):
        other = self._project()
        publish(self._event(ProjectCreated))
        publish(self._event(ProjectCreated, project=other))
        seen: list[str] = []

        def infer(project):
            # First run for self.project: a push lands while it is executing,
            # deferring a twin that must run after this one finishes.
            if project.pk == self.project.pk and str(project.pk) not in seen:
                publish(self._event())
                self.assertEqual(_todo_count(self.lock), 1)
            seen.append(str(project.pk))
            _ok(project)

        self._drain(infer=infer)

        self.assertEqual(seen.count(str(self.project.pk)), 2, "twin did not run")
        self.assertEqual(seen.count(str(other.pk)), 1)
        rows = _map_jobs()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["status"] for r in rows}, {"succeeded"})
        self._assert_settled(self.project, other)
