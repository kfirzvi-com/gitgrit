from django.test import TestCase
from model_bakery import baker

from app import tasks
from app.domain.models import Project
from tests.support import MonkeyPatchMixin


def _queue_job(queueing_lock: str) -> None:
    """A ``todo`` job holding ``queueing_lock``, deferred the way
    ``app.application.subscribers`` does it."""
    tasks.infer_project_dependencies.configure(
        lock=queueing_lock, queueing_lock=queueing_lock
    ).defer(project_id="00000000-0000-0000-0000-000000000000")


class InferProjectDependenciesTaskTests(MonkeyPatchMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.sleeps: list[float] = []
        self.monkeypatch.setattr(tasks, "_sleep", self.sleeps.append)

    def _project(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        return baker.make("app.Project", tenant=tenant, platform_connection=conn)

    def _inference(self, outcomes):
        """Stub ``infer_and_store``; each call pops the next outcome, an
        exception instance to raise or anything else to return."""
        calls = []

        def fake(project):
            calls.append(project.id)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        self.monkeypatch.setattr("app.application.dependency_agent.infer_and_store", fake)
        return calls

    def test_task_declares_no_procrastinate_retry(self):
        """A Procrastinate retry moves the ``doing`` row back to ``todo``, which
        collides with a coalesced twin and leaves a zombie. Retries live inside
        the task instead."""
        self.assertIsNone(tasks.infer_project_dependencies.retry_strategy)

    def test_failure_on_every_attempt_raises_after_the_last_one(self):
        project = self._project()
        calls = self._inference([RuntimeError("provider said no")] * tasks.INFERENCE_ATTEMPTS)

        with self.assertRaises(RuntimeError):
            tasks.infer_project_dependencies.func(project_id=str(project.id))

        self.assertEqual(len(calls), tasks.INFERENCE_ATTEMPTS)
        self.assertEqual(
            self.sleeps,
            [tasks.INFERENCE_RETRY_DELAY_SECONDS * n for n in range(1, tasks.INFERENCE_ATTEMPTS)],
        )
        project.refresh_from_db()
        self.assertEqual(project.deps_status, Project.DepsStatus.FAILED)
        self.assertIn("provider said no", project.deps_error)

    def test_transient_failure_then_success_ends_ok(self):
        project = self._project()
        calls = self._inference([RuntimeError("blip"), None])

        result = tasks.infer_project_dependencies.func(project_id=str(project.id))

        self.assertIsNone(result)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.sleeps, [tasks.INFERENCE_RETRY_DELAY_SECONDS])
        project.refresh_from_db()
        self.assertNotEqual(project.deps_status, Project.DepsStatus.FAILED)
        self.assertEqual(project.deps_error, "")

    def test_queued_twin_is_untouched_by_a_failing_run(self):
        """The twin waits in ``todo`` for the ``lock``; this job must end
        (raise) so the twin can be fetched, and must never write to it."""
        project = self._project()
        lock = f"deps:{project.id}"
        _queue_job(lock)
        self._inference([RuntimeError("provider said no")] * tasks.INFERENCE_ATTEMPTS)

        with self.assertRaises(RuntimeError):
            tasks.infer_project_dependencies.func(project_id=str(project.id))

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM procrastinate_jobs WHERE queueing_lock = %s", [lock]
            )
            self.assertEqual([r[0] for r in cursor.fetchall()], ["todo"])

    def test_success_path_unchanged(self):
        project = self._project()
        calls = self._inference([None])

        tasks.infer_project_dependencies.func(project_id=str(project.id))

        self.assertEqual(calls, [project.id])
        self.assertEqual(self.sleeps, [])

    def test_missing_project_is_a_noop(self):
        calls = self._inference([])

        tasks.infer_project_dependencies.func(project_id="00000000-0000-0000-0000-000000000000")

        self.assertEqual(calls, [])
