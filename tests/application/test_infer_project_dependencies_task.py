from unittest.mock import MagicMock

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
    def _project(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        return baker.make("app.Project", tenant=tenant, platform_connection=conn)

    def _context(self, queueing_lock):
        return MagicMock(job=MagicMock(queueing_lock=queueing_lock))

    def _failing_inference(self):
        def boom(project):
            raise RuntimeError("provider said no")

        self.monkeypatch.setattr(
            "app.application.dependency_agent.infer_and_store", boom
        )

    def test_failure_with_no_queued_twin_raises_so_procrastinate_retries(self):
        project = self._project()
        self._failing_inference()

        with self.assertRaises(RuntimeError):
            tasks.infer_project_dependencies.func(
                self._context(f"deps:{project.id}"), project_id=str(project.id)
            )

        project.refresh_from_db()
        self.assertEqual(project.deps_status, Project.DepsStatus.FAILED)
        self.assertIn("provider said no", project.deps_error)

    def test_failure_with_queued_twin_ends_without_retry(self):
        """Regression: retrying here collides with the twin's ``todo`` row on
        the one-todo-per-queueing_lock index, leaving this job a zombie in
        ``doing`` on a live worker and the twin blocked behind its lock."""
        project = self._project()
        lock = f"deps:{project.id}"
        _queue_job(lock)
        self._failing_inference()

        result = tasks.infer_project_dependencies.func(
            self._context(lock), project_id=str(project.id)
        )

        self.assertIsNone(result)
        project.refresh_from_db()
        self.assertEqual(project.deps_status, Project.DepsStatus.FAILED)
        self.assertIn("provider said no", project.deps_error)

    def test_twin_on_another_lock_does_not_suppress_retry(self):
        project = self._project()
        _queue_job("deps:some-other-project")
        self._failing_inference()

        with self.assertRaises(RuntimeError):
            tasks.infer_project_dependencies.func(
                self._context(f"deps:{project.id}"), project_id=str(project.id)
            )

    def test_success_path_unchanged(self):
        project = self._project()
        calls = []
        self.monkeypatch.setattr(
            "app.application.dependency_agent.infer_and_store",
            lambda p: calls.append(p.id),
        )

        tasks.infer_project_dependencies.func(
            self._context(f"deps:{project.id}"), project_id=str(project.id)
        )

        self.assertEqual(calls, [project.id])
