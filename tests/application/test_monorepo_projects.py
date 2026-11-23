"""A monorepo holds one project per app or service, each rooted at its own
directory: they share the repository's webhook, a push runs only the projects
whose directories it changed, the sandbox reads each from its root, and the
CLI picks the project the caller stands in."""
from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app.application import project_management as pm
from app.application.project_service import ProjectService
from app.application.standard_runs import enqueue_for_event
from app.domain.events import DomainEvent
from app.domain.models import AuthMethod
from app.domain.projects import InvalidRootPath
from tests.support import queued_standards_run_inline

REPO = {
    "external_id": "77",
    "name": "shop",
    "full_path": "acme/shop",
    "web_url": "https://github.com/acme/shop",
    "default_branch": "main",
    "description": "",
}
TREE = ["README.md", "apps/web/package.json", "apps/web/src/a.ts", "services/api/main.go", "services/api/go.mod"]


def _client():
    client = mock.Mock()
    client.search_projects.side_effect = lambda q="": [dict(REPO)]
    client.get_languages.return_value = ["Go", "TypeScript"]
    client.get_topics.return_value = []
    client.get_tree.return_value = TREE
    client.create_webhook.side_effect = ["hook-1", "hook-2"]
    return client


class AddingProjectsInOneRepositoryTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.pat = baker.make(
            "app.PlatformConnection", tenant=self.tenant, platform="github", auth_method=AuthMethod.PAT
        )
        patch = mock.patch("app.application.project_management.get_platform_client", return_value=_client())
        self.client = patch.start().return_value
        self.addCleanup(patch.stop)

    def test_projects_at_different_paths_share_one_webhook(self):
        root = pm.add_project(self.tenant, None, self.pat, REPO).project
        web = pm.add_project(self.tenant, None, self.pat, REPO, root_path="/apps/web/").project

        self.assertEqual(web.root_path, "apps/web")
        self.assertEqual(web.name, "shop/apps/web")
        self.assertEqual(self.client.create_webhook.call_count, 1)
        self.assertEqual((web.webhook_id, web.webhook_secret), (root.webhook_id, root.webhook_secret))

    def test_a_rooted_project_counts_languages_from_its_own_files(self):
        web = pm.add_project(self.tenant, None, self.pat, REPO, root_path="apps/web").project
        root = pm.add_project(self.tenant, None, self.pat, REPO).project

        self.assertEqual(web.languages, ["TypeScript"])
        self.assertEqual(root.languages, ["Go", "TypeScript"])

    def test_the_same_path_twice_is_already_added(self):
        pm.add_project(self.tenant, None, self.pat, REPO, root_path="apps/web")
        with self.assertRaises(pm.AlreadyAdded):
            pm.add_project(self.tenant, None, self.pat, REPO, root_path="apps/web/")

    def test_a_path_leaving_the_repository_is_refused(self):
        with self.assertRaises(InvalidRootPath):
            pm.add_project(self.tenant, None, self.pat, REPO, root_path="../other")

    def test_search_lists_the_paths_already_added(self):
        pm.add_project(self.tenant, None, self.pat, REPO, root_path="apps/web")
        [result] = pm.search_repositories(self.tenant, self.pat, "shop")
        self.assertEqual(result["added_paths"], ["apps/web"])
        self.assertFalse(result["already_added"])

    def test_the_webhook_stays_while_another_project_uses_it(self):
        root = pm.add_project(self.tenant, None, self.pat, REPO).project
        web = pm.add_project(self.tenant, None, self.pat, REPO, root_path="apps/web").project

        pm.delete_project(self.tenant, None, web.pk)
        self.client.delete_webhook.assert_not_called()

        pm.delete_project(self.tenant, None, root.pk)
        self.client.delete_webhook.assert_called_once_with("77", "hook-1")


def _passed():
    return {"passed": True, "score": 100, "message": "ok", "details": {}}


class PushToMonorepoTests(TestCase):
    def setUp(self):
        runner = mock.patch("app.application.standard_engine.SandboxRunner")
        self.runner = runner.start().return_value
        self.addCleanup(runner.stop)
        self.runner.run.side_effect = lambda code, cfg: _passed()
        inline = queued_standards_run_inline()
        inline.__enter__()
        self.addCleanup(inline.__exit__, None, None, None)

        self.tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=self.tenant, platform="github", access_token="t")
        standard = baker.make(
            "app.Standard", tenant=self.tenant, enabled=True, draft=False,
            criteria={"events": ["push"], "ref": "", "languages": []},
        )
        self.projects = {}
        for path in ("", "apps/web", "services/api"):
            p = baker.make(
                "app.Project", tenant=self.tenant, platform="github", platform_connection=conn,
                external_id="77", full_path="acme/shop", root_path=path, languages=[],
            )
            p.standards.add(standard)
            self.projects[path] = p

    def _push(self, changed, base_sha="b" * 40):
        return DomainEvent(
            event_type="push", platform="github", external_project_id="77", ref="refs/heads/main",
            commit_sha="a" * 40, changed_paths=changed, base_sha=base_sha,
        )

    def _ran(self):
        return sorted(cfg["root_path"] for (_, cfg), _ in self.runner.run.call_args_list)

    def test_a_push_runs_the_repository_and_the_projects_it_touched(self):
        enqueue_for_event(self._push(("services/api/main.go",)))
        self.assertEqual(self._ran(), ["", "services/api"])

    def test_unknown_changes_are_asked_of_the_platform(self):
        with mock.patch("app.application.changed_paths.get_platform_client") as client:
            client.return_value.changed_files.return_value = ["apps/web/src/a.ts"]
            enqueue_for_event(self._push(None))
        client.return_value.changed_files.assert_called_once_with("77", "acme/shop", "b" * 40, "a" * 40)
        self.assertEqual(self._ran(), ["", "apps/web"])

    def test_changes_nobody_can_list_run_every_project(self):
        enqueue_for_event(self._push(None, base_sha=""))
        self.assertEqual(self._ran(), ["", "apps/web", "services/api"])


class ResolveInMonorepoTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=self.tenant, platform="github")
        for path in ("", "apps/web", "apps/web/admin"):
            baker.make(
                "app.Project", tenant=self.tenant, platform_connection=conn, external_id="77",
                full_path="acme/shop", root_path=path, name=f"shop/{path}",
            )

    def _resolve(self, path):
        return ProjectService().resolve_project(self.tenant, "acme/shop", None, path)["root_path"]

    def test_the_innermost_project_wins(self):
        self.assertEqual(self._resolve("apps/web/admin/src"), "apps/web/admin")
        self.assertEqual(self._resolve("apps/web/src"), "apps/web")
        self.assertEqual(self._resolve("docs"), "")
        self.assertEqual(self._resolve(None), "")


class RootedCommitListTests(TestCase):
    def test_a_rooted_project_lists_and_pins_commits_touching_its_directory(self):
        from app.application import commit_checks

        conn = baker.make("app.PlatformConnection", platform="github")
        project = baker.make(
            "app.Project", tenant=conn.tenant, platform_connection=conn, external_id="77",
            full_path="acme/shop", root_path="apps/web",
        )
        with mock.patch("app.application.commit_checks._client") as client:
            client.return_value.list_commits.return_value = []
            client.return_value.head_commit.return_value = {"sha": "a" * 40, "date": ""}
            commit_checks.branch_commits(project, "main")
            commit_checks.resolve_head_commit(project, "main")
        self.assertEqual(client.return_value.list_commits.call_args.kwargs["path"], "apps/web")
        self.assertEqual(client.return_value.head_commit.call_args.kwargs["path"], "apps/web")
