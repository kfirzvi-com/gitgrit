"""The project page caches the platform's branch and commit lists for a
minute, because it re-renders every few seconds while runs are in flight.
Only answers are cached, and a push webhook clears a project's cache."""
from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app.application import commit_checks
from app.application.commit_checks import branch_commits, branches, forget_platform_lists
from app.application.standard_engine import StandardEngine
from app.application.standard_runs import enqueue_for_event

COMMIT = {"sha": "a" * 40, "message": "m", "author": "Dana", "date": "2026-10-01T10:00:00Z", "url": ""}


class PlatformListsCacheTests(TestCase):
    def setUp(self):
        self.project = baker.make("app.Project", tenant=baker.make("app.Tenant"), default_branch="main")
        self.platform = mock.Mock()
        self.platform.list_branches.return_value = ["main", "feature/x"]
        self.platform.list_commits.return_value = [COMMIT]
        patch = mock.patch.object(commit_checks, "_client", return_value=self.platform)
        patch.start()
        self.addCleanup(patch.stop)

    def test_repeat_renders_reuse_the_platforms_answers(self):
        for _ in range(3):
            branches(self.project)
            branch_commits(self.project, "main")

        self.assertEqual(self.platform.list_branches.call_count, 1)
        self.assertEqual(self.platform.list_commits.call_count, 1)

    def test_each_branch_and_page_is_its_own_entry(self):
        branch_commits(self.project, "main")
        branch_commits(self.project, "main", page=2)
        branch_commits(self.project, "feature/x")

        self.assertEqual(self.platform.list_commits.call_count, 3)

    def test_a_failure_is_not_cached(self):
        self.platform.list_commits.side_effect = [RuntimeError("down"), [COMMIT]]

        branch_commits(self.project, "main")
        rows, _ = branch_commits(self.project, "main")

        self.assertEqual([r.sha for r in rows], ["a" * 40])
        self.assertEqual(self.platform.list_commits.call_count, 2)

    def test_forgetting_a_project_asks_the_platform_again(self):
        branches(self.project)
        forget_platform_lists([self.project])
        branches(self.project)

        self.assertEqual(self.platform.list_branches.call_count, 2)

    def test_a_push_webhook_forgets_its_projects_even_a_branch_deletion(self):
        branches(self.project)
        event = mock.Mock(deleted=True)
        with mock.patch.object(
            StandardEngine, "resolve_projects", return_value=type(self.project).objects.filter(pk=self.project.pk)
        ):
            self.assertEqual(enqueue_for_event(event), [])
        branches(self.project)

        self.assertEqual(self.platform.list_branches.call_count, 2)
