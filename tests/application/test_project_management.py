"""Adding and managing projects, the same way from the browser and the API.

A repository is found by path among those its connection reaches; adding it
reads its metadata, registers a webhook unless the connection is a GitHub App,
and queues its attached runnable standards once. Attaching more queues only the
new ones."""
from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app.application import project_management as pm
from app.application.errors import NotFoundError
from app.domain.models import AuthMethod, Project

REPO = {
    "external_id": "101",
    "name": "auth-service",
    "full_path": "acme/auth-service",
    "web_url": "https://github.com/acme/auth-service",
    "default_branch": "main",
    "description": "Identity",
}


def _client(repos=(REPO,)):
    client = mock.Mock()
    client.search_projects.side_effect = lambda q="": [
        dict(r) for r in repos if q.lower() in r["full_path"].lower()
    ]
    client.get_languages.return_value = ["Python"]
    client.get_topics.return_value = ["identity"]
    client.create_webhook.return_value = "hook-1"
    return client


class ProjectManagementTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.user = baker.make("app.User")
        self.pat = baker.make(
            "app.PlatformConnection", tenant=self.tenant, platform="github",
            display_name="GitHub", auth_method=AuthMethod.PAT,
        )
        self.app = baker.make(
            "app.PlatformConnection", tenant=self.tenant, platform="github",
            display_name="GitHub App (acme)", auth_method=AuthMethod.GITHUB_APP,
        )
        self.readme = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)
        self.license = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)
        self.client_patch = mock.patch(
            "app.application.project_management.get_platform_client", return_value=_client()
        )
        self.platform = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        runs = mock.patch(
            "app.application.standard_runs.run_standards.configure"
        )
        runs.start()
        self.addCleanup(runs.stop)

    def test_a_repository_is_found_by_its_path_in_any_case_or_by_id(self):
        self.assertEqual(pm.find_repository(self.tenant, self.pat, "ACME/auth-service")["external_id"], "101")
        self.assertEqual(pm.find_repository(self.tenant, self.pat, "acme/auth-service.git")["name"], "auth-service")

    def test_a_repository_the_connection_cannot_reach_is_not_found(self):
        with self.assertRaises(NotFoundError):
            pm.find_repository(self.tenant, self.pat, "acme/billing")

    def test_search_marks_repositories_already_added(self):
        pm.add_project(self.tenant, self.user, self.pat, REPO)

        [result] = pm.search_repositories(self.tenant, self.pat, "auth")

        self.assertTrue(result["already_added"])

    def test_a_platform_failure_while_searching_is_a_platform_error(self):
        self.platform.return_value.search_projects.side_effect = RuntimeError("401")

        with self.assertRaises(pm.PlatformError):
            pm.search_repositories(self.tenant, self.pat, "auth")

    def test_adding_through_a_token_connection_registers_a_webhook_and_reads_metadata(self):
        added = pm.add_project(self.tenant, self.user, self.pat, REPO)

        project = added.project
        self.assertTrue(added.webhook_ok)
        self.assertEqual(project.webhook_id, "hook-1")
        self.assertEqual(project.languages, ["Python"])
        self.assertEqual(project.tags, ["identity"])
        self.assertEqual(project.full_path, "acme/auth-service")

    def test_adding_through_the_github_app_registers_no_webhook(self):
        added = pm.add_project(self.tenant, self.user, self.app, REPO)

        self.platform.return_value.create_webhook.assert_not_called()
        self.assertTrue(added.webhook_ok)
        self.assertFalse(added.project.webhook_id)

    def test_a_refused_webhook_still_adds_the_project(self):
        self.platform.return_value.create_webhook.side_effect = RuntimeError("403")

        added = pm.add_project(self.tenant, None, self.pat, REPO)

        self.assertFalse(added.webhook_ok)
        self.assertTrue(Project.objects.filter(pk=added.project.pk).exists())

    def test_attached_standards_are_queued_once_and_none_by_default(self):
        bare = pm.add_project(self.tenant, self.user, self.app, REPO)
        self.assertIsNone(bare.runs)
        self.assertEqual(bare.project.standards.count(), 0)
        pm.delete_project(self.tenant, self.user, bare.project.pk)

        added = pm.add_project(
            self.tenant, self.user, self.app, REPO, standard_ids=[self.readme.pk, self.license.pk]
        )

        self.assertEqual(added.runs["queued"], 2)

    def test_adding_the_same_repository_twice_is_refused(self):
        pm.add_project(self.tenant, self.user, self.pat, REPO)

        with self.assertRaises(pm.AlreadyAdded):
            pm.add_project(self.tenant, self.user, self.pat, REPO)

    def test_unknown_lifecycles_and_standards_are_refused(self):
        with self.assertRaises(ValueError):
            pm.add_project(self.tenant, self.user, self.pat, REPO, lifecycle="someday")
        other_workspace_standard = baker.make("app.Standard")
        with self.assertRaises(NotFoundError):
            pm.add_project(
                self.tenant, self.user, self.pat, REPO, standard_ids=[other_workspace_standard.pk]
            )

    def test_attaching_queues_only_the_newly_attached(self):
        project = pm.add_project(
            self.tenant, self.user, self.app, REPO, standard_ids=[self.readme.pk]
        ).project

        result = pm.attach_standards(project, [self.readme.pk, self.license.pk])

        self.assertEqual({s.pk for s in result["standards"]}, {self.readme.pk, self.license.pk})
        self.assertEqual(result["runs"]["queued"], 1)

    def test_detaching_runs_nothing(self):
        project = pm.add_project(
            self.tenant, self.user, self.app, REPO, standard_ids=[self.readme.pk, self.license.pk]
        ).project

        result = pm.detach_standards(project, [self.readme.pk])

        self.assertEqual([s.pk for s in result["standards"]], [self.license.pk])
        self.assertIsNone(result["runs"])

    def test_editing_changes_only_what_is_given(self):
        project = pm.add_project(self.tenant, self.user, self.app, REPO, owner="platform").project

        pm.update_project(self.tenant, project.pk, lifecycle="production")

        project.refresh_from_db()
        self.assertEqual(project.lifecycle, "production")
        self.assertEqual(project.owner, "platform")

    def test_removing_deletes_the_webhook_and_the_project(self):
        project = pm.add_project(self.tenant, self.user, self.pat, REPO).project

        name = pm.delete_project(self.tenant, self.user, project.pk)

        self.assertEqual(name, "auth-service")
        self.platform.return_value.delete_webhook.assert_called_once_with("101", "hook-1")
        self.assertFalse(Project.objects.filter(pk=project.pk).exists())

    def test_another_workspaces_project_is_not_found(self):
        project = pm.add_project(self.tenant, self.user, self.pat, REPO).project
        other = baker.make("app.Tenant")

        with self.assertRaises(NotFoundError):
            pm.delete_project(other, self.user, project.pk)
        with self.assertRaises(NotFoundError):
            pm.get_connection(other, self.pat.pk)
