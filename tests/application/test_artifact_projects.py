"""Artifact projects end to end, short of the container: creating them,
uploading commits, and running standards on a commit's files.

The sandbox runner is mocked; what it is handed (the mounted directory and
the input config) is what these tests check.
"""
from pathlib import Path
from unittest import mock

from django.core.files.storage import storages
from django.test import TestCase
from model_bakery import baker

from app import tasks
from app.application import artifact_service
from app.application.commit_checks import branch_commits, branches, commit_results
from app.application.errors import NotFoundError
from app.application.standard_runs import enqueue_manual_run
from app.domain.models import (
    CommitCheck,
    Platform,
    PlatformConnection,
    ArtifactCommit,
    StandardExecution,
)
from app.domain.artifacts import UploadRejected
from tests.infrastructure.test_archives import make_zip
from tests.support import defer_patch

BUILD_V1 = make_zip({"dist/index.html": b"<html>v1</html>", "dist/app.js": b"start()"})
BUILD_V2 = make_zip({"dist/index.html": b"<html>v2</html>", "dist/app.js": b"start(2)"})
PASSED = {"passed": True, "score": 100, "message": "OK", "details": {}}


def _push_standard(tenant, **kw):
    criteria = kw.pop("criteria", {"events": ["push"]})
    return baker.make("app.Standard", tenant=tenant, criteria=criteria, **kw)


class CreateUploadProjectTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def test_a_new_project_hangs_off_the_workspace_upload_connection(self):
        result = artifact_service.create_artifact_project(
            self.tenant, name="Storefront", external_id="ext-42", stack="Acme Web"
        )

        project = result.project
        self.assertTrue(result.created)
        self.assertTrue(project.is_artifact)
        self.assertEqual(project.platform_connection.platform, Platform.ARTIFACT)
        self.assertEqual(project.root_component.stacks.get().name, "Acme Web")

    def test_creating_again_returns_the_same_project(self):
        first = artifact_service.create_artifact_project(self.tenant, name="A", external_id="g1")
        again = artifact_service.create_artifact_project(self.tenant, name="A", external_id="g1")

        self.assertFalse(again.created)
        self.assertEqual(again.project.pk, first.project.pk)
        self.assertEqual(
            PlatformConnection.objects.filter(tenant=self.tenant, platform=Platform.ARTIFACT).count(), 1
        )

    def test_an_existing_stack_is_reused_by_name(self):
        artifact_service.create_artifact_project(self.tenant, name="A", external_id="g1", stack="Web Team")
        artifact_service.create_artifact_project(self.tenant, name="B", external_id="g2", stack="Web Team")

        self.assertEqual(self.tenant.stacks.filter(name="Web Team").count(), 1)
        self.assertEqual(self.tenant.stacks.get().components.count(), 2)

    def test_by_default_it_gets_no_standards_like_a_repository(self):
        _push_standard(self.tenant)

        project = artifact_service.create_artifact_project(self.tenant, name="A", external_id="g1").project

        self.assertEqual(list(project.standards.all()), [])

    def test_named_standards_are_attached(self):
        _push_standard(self.tenant)
        chosen = baker.make("app.Standard", tenant=self.tenant)

        project = artifact_service.create_artifact_project(
            self.tenant, name="A", external_id="g1", standard_ids=[str(chosen.pk)]
        ).project

        self.assertEqual(list(project.standards.all()), [chosen])

    def test_a_standard_from_another_workspace_is_not_found(self):
        foreign = baker.make("app.Standard")
        with self.assertRaises(NotFoundError):
            artifact_service.create_artifact_project(
                self.tenant, name="A", external_id="g1", standard_ids=[str(foreign.pk)]
            )

    def test_the_project_triggers_no_dependency_analysis(self):
        with mock.patch("app.application.subscribers._enqueue_dependency_refresh") as refresh:
            artifact_service.create_artifact_project(
                self.tenant, name="A", external_id="g1", stack="Web Team"
            )
        refresh.assert_not_called()


class UploadCommitTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.standard = _push_standard(self.tenant, code="CODE")
        self.project = artifact_service.create_artifact_project(
            self.tenant, name="Storefront", external_id="ext-42", standard_ids=[str(self.standard.pk)]
        ).project

    def _upload(self, data=BUILD_V1, **kw):
        with defer_patch() as configure:
            result = artifact_service.upload_commit(self.project, data, author="platform", **kw)
        return result, configure

    def test_an_upload_is_stored_and_checked_like_a_pushed_commit(self):
        result, configure = self._upload(message="Release 1.0.0\n\nfirst cut")

        commit = result.commit
        self.assertTrue(result.created)
        self.assertEqual(commit.title, "Release 1.0.0")
        self.assertEqual(commit.branch, "main")
        self.assertEqual(commit.file_count, 2)
        check = CommitCheck.objects.get(project=self.project)
        self.assertEqual(check.commit_sha, commit.sha)
        self.assertEqual(check.branch, "main")
        self.assertEqual(check.event_type, "push")
        self.assertEqual(result.run["queued"], 1)
        configure.return_value.defer.assert_called_once()

    def test_the_languages_come_from_the_uploaded_files(self):
        self._upload()
        self.project.refresh_from_db()
        self.assertEqual(sorted(self.project.languages), ["HTML", "JavaScript"])

    def test_the_same_bytes_again_are_the_same_commit_but_checked_again(self):
        first, _ = self._upload()
        again, _ = self._upload()

        self.assertFalse(again.created)
        self.assertEqual(again.commit.pk, first.commit.pk)
        self.assertEqual(ArtifactCommit.objects.count(), 1)
        self.assertEqual(CommitCheck.objects.filter(project=self.project).count(), 2)

    def test_an_upload_lands_on_the_branch_it_names(self):
        result, _ = self._upload(branch="review")
        self.assertEqual(result.commit.branch, "review")
        self.assertEqual(CommitCheck.objects.get().branch, "review")

    def test_only_standards_that_run_on_pushes_are_queued(self):
        pr_only = baker.make("app.Standard", tenant=self.tenant, criteria={"events": ["pull_request"]})
        self.project.standards.add(pr_only)

        result, _ = self._upload()

        self.assertEqual(
            [e["standard_id"] for e in result.run["executions"]], [str(self.standard.pk)]
        )

    def test_a_rejected_archive_stores_nothing(self):
        with self.assertRaises(UploadRejected):
            self._upload(make_zip({"../escape.js": b"x"}))
        self.assertFalse(ArtifactCommit.objects.exists())
        self.assertFalse(CommitCheck.objects.exists())

    def test_a_git_project_takes_no_uploads(self):
        git_project = baker.make("app.Project", tenant=self.tenant)
        with self.assertRaises(ValueError):
            artifact_service.upload_commit(git_project, BUILD_V1)

    def test_a_manual_run_before_any_upload_queues_nothing(self):
        with defer_patch() as configure:
            self.assertIsNone(enqueue_manual_run(self.project, [self.standard]))
        configure.assert_not_called()


class RunOnCommitTests(TestCase):
    """The ``run_standards`` job on an artifact project's commit."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.standard = _push_standard(self.tenant, code="CODE")
        self.project = artifact_service.create_artifact_project(
            self.tenant, name="Storefront", external_id="ext-42", standard_ids=[str(self.standard.pk)]
        ).project
        self.seen = []

    def _runner(self):
        def run(code, config, project_dir=None):
            files = sorted(p.relative_to(project_dir).as_posix() for p in Path(project_dir).rglob("*") if p.is_file())
            self.seen.append({"config": config, "dir": project_dir, "files": files,
                              "index": (Path(project_dir) / "index.html").read_text()})
            return PASSED

        runner = mock.Mock()
        runner.run.side_effect = run
        return mock.patch("app.application.standard_engine.SandboxRunner", return_value=runner)

    def _upload_and_run(self, data, **kw):
        with defer_patch() as configure:
            artifact_service.upload_commit(self.project, data, **kw)
        job = configure.return_value.defer.call_args.kwargs
        with self._runner():
            tasks.run_standards.func(**job)
        return StandardExecution.objects.filter(pk__in=job["execution_ids"])

    def test_the_sandbox_reads_the_commit_files_mounted_from_disk(self):
        executions = self._upload_and_run(BUILD_V1)

        self.assertEqual(executions.get().status, StandardExecution.Status.PASSED)
        seen = self.seen[0]
        self.assertEqual(seen["files"], ["app.js", "index.html"])
        self.assertEqual(seen["index"], "<html>v1</html>")
        self.assertEqual(seen["config"]["platform"], "artifact")
        self.assertNotIn("access_token", seen["config"])
        self.assertEqual(seen["config"]["ref"], ArtifactCommit.objects.get().sha)

    def test_the_extracted_files_are_removed_after_the_job(self):
        self._upload_and_run(BUILD_V1)
        self.assertFalse(Path(self.seen[0]["dir"]).exists())

    def test_each_commit_is_read_at_its_own_files(self):
        self._upload_and_run(BUILD_V1)
        self._upload_and_run(BUILD_V2)
        self.assertEqual([s["index"] for s in self.seen], ["<html>v1</html>", "<html>v2</html>"])

    def test_a_run_on_a_branch_with_no_commit_is_an_error_not_a_crash(self):
        with defer_patch() as configure:
            artifact_service.upload_commit(self.project, BUILD_V1)
        ArtifactCommit.objects.all().delete()  # gone before the job ran
        job = configure.return_value.defer.call_args.kwargs
        with self._runner():
            tasks.run_standards.func(**job)

        execution = StandardExecution.objects.get()
        self.assertEqual(execution.status, StandardExecution.Status.ERROR)
        self.assertIn("No commit of Storefront has been uploaded", execution.message)


class CommitHistoryTests(TestCase):
    """The project page's branch and commit history reads uploaded commits."""

    def setUp(self):
        tenant = baker.make("app.Tenant")
        standard = _push_standard(tenant)
        self.project = artifact_service.create_artifact_project(
            tenant, name="Storefront", external_id="ext-42", standard_ids=[str(standard.pk)]
        ).project
        with defer_patch():
            self.v1 = artifact_service.upload_commit(self.project, BUILD_V1, message="1.0", author="platform").commit
            self.v2 = artifact_service.upload_commit(self.project, BUILD_V2, message="1.1", author="platform").commit
            artifact_service.upload_commit(self.project, make_zip({"x.js": b"x"}), branch="review")

    def test_upload_branches_are_the_branches(self):
        self.assertEqual(branches(self.project), ["main", "review"])

    def test_uploads_are_the_commits_newest_first(self):
        rows, has_more = branch_commits(self.project, "main")
        self.assertEqual([r.sha for r in rows], [self.v2.sha, self.v1.sha])
        self.assertEqual([r.title for r in rows], ["1.1", "1.0"])
        self.assertEqual(rows[0].author, "platform")
        self.assertFalse(has_more)

    def test_a_new_upload_shows_at_once_despite_the_cached_list(self):
        branch_commits(self.project, "main")  # cached
        with defer_patch():
            v3 = artifact_service.upload_commit(self.project, make_zip({"y.js": b"y"}), message="1.2").commit
        rows, _ = branch_commits(self.project, "main")
        self.assertEqual(rows[0].sha, v3.sha)

    def test_an_upload_check_reports_through_the_commit_lookup(self):
        row = commit_results(self.project, self.v2.sha)
        self.assertTrue(row.checked)
        self.assertEqual(row.running, 1)  # queued, the worker has not run it yet


class DeletingArchivesTests(TestCase):
    """A deleted project's (or workspace's) archives leave the storage too."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = artifact_service.create_artifact_project(
            self.tenant, name="Storefront", external_id="ext-42"
        ).project
        with defer_patch():
            self.commit = artifact_service.upload_commit(self.project, BUILD_V1).commit
        self.storage = storages["uploads"]

    def test_deleting_the_project_deletes_its_archives(self):
        self.assertTrue(self.storage.exists(self.commit.archive_key))
        with self.captureOnCommitCallbacks(execute=True):
            self.project.delete()
        self.assertFalse(self.storage.exists(self.commit.archive_key))

    def test_deleting_the_workspace_deletes_them_too(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.tenant.delete()
        self.assertFalse(self.storage.exists(self.commit.archive_key))

    def test_a_rolled_back_delete_keeps_the_archive(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.project.delete()
        self.assertEqual(len(callbacks), 1)  # only runs if the delete commits
        self.assertTrue(self.storage.exists(self.commit.archive_key))

    def test_a_storage_failure_is_logged_not_raised(self):
        with mock.patch.object(type(self.storage), "delete", side_effect=OSError("down")), \
                self.assertLogs("app.infrastructure.upload_storage", "ERROR"), \
                self.captureOnCommitCallbacks(execute=True):
            self.project.delete()
