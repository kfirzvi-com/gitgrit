"""Upload projects end to end, short of the container: creating them,
uploading versions, and running standards on a version's files.

The sandbox runner is mocked; what it is handed (the mounted directory and
the input config) is what these tests check.
"""
from pathlib import Path
from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app import tasks
from app.application import upload_service
from app.application.commit_checks import branch_commits, branches, commit_results
from app.application.errors import NotFoundError
from app.application.standard_runs import enqueue_manual_run
from app.domain.models import (
    CommitCheck,
    Platform,
    PlatformConnection,
    ProjectVersion,
    StandardExecution,
)
from app.domain.uploads import UploadRejected
from tests.infrastructure.test_archives import make_zip
from tests.support import defer_patch

GAME_V1 = make_zip({"dist/index.html": b"<html>v1</html>", "dist/game.js": b"start()"})
GAME_V2 = make_zip({"dist/index.html": b"<html>v2</html>", "dist/game.js": b"start(2)"})
PASSED = {"passed": True, "score": 100, "message": "OK", "details": {}}


def _upload_standard(tenant, **kw):
    criteria = kw.pop("criteria", {"events": ["upload"]})
    return baker.make("app.Standard", tenant=tenant, criteria=criteria, **kw)


class CreateUploadProjectTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")

    def test_a_new_project_hangs_off_the_workspace_upload_connection(self):
        result = upload_service.create_upload_project(
            self.tenant, name="Space Race", external_id="game-42", stack="Acme Studio"
        )

        project = result.project
        self.assertTrue(result.created)
        self.assertTrue(project.is_upload)
        self.assertEqual(project.platform_connection.platform, Platform.UPLOAD)
        self.assertEqual(project.root_component.stacks.get().name, "Acme Studio")

    def test_creating_again_returns_the_same_project(self):
        first = upload_service.create_upload_project(self.tenant, name="A", external_id="g1")
        again = upload_service.create_upload_project(self.tenant, name="A", external_id="g1")

        self.assertFalse(again.created)
        self.assertEqual(again.project.pk, first.project.pk)
        self.assertEqual(
            PlatformConnection.objects.filter(tenant=self.tenant, platform=Platform.UPLOAD).count(), 1
        )

    def test_an_existing_stack_is_reused_by_name(self):
        upload_service.create_upload_project(self.tenant, name="A", external_id="g1", stack="Studio")
        upload_service.create_upload_project(self.tenant, name="B", external_id="g2", stack="Studio")

        self.assertEqual(self.tenant.stacks.filter(name="Studio").count(), 1)
        self.assertEqual(self.tenant.stacks.get().components.count(), 2)

    def test_by_default_it_gets_the_published_standards_that_run_on_uploads(self):
        on_upload = _upload_standard(self.tenant)
        _upload_standard(self.tenant, criteria={"events": ["push"]})
        _upload_standard(self.tenant, draft=True, enabled=False)

        project = upload_service.create_upload_project(self.tenant, name="A", external_id="g1").project

        self.assertEqual(list(project.standards.all()), [on_upload])

    def test_named_standards_replace_the_default(self):
        _upload_standard(self.tenant)
        chosen = baker.make("app.Standard", tenant=self.tenant)

        project = upload_service.create_upload_project(
            self.tenant, name="A", external_id="g1", standard_ids=[str(chosen.pk)]
        ).project

        self.assertEqual(list(project.standards.all()), [chosen])

    def test_a_standard_from_another_workspace_is_not_found(self):
        foreign = baker.make("app.Standard")
        with self.assertRaises(NotFoundError):
            upload_service.create_upload_project(
                self.tenant, name="A", external_id="g1", standard_ids=[str(foreign.pk)]
            )

    def test_the_project_triggers_no_dependency_analysis(self):
        with mock.patch("app.application.subscribers._enqueue_dependency_refresh") as refresh:
            upload_service.create_upload_project(
                self.tenant, name="A", external_id="g1", stack="Studio"
            )
        refresh.assert_not_called()


class UploadVersionTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.standard = _upload_standard(self.tenant, code="CODE")
        self.project = upload_service.create_upload_project(
            self.tenant, name="Space Race", external_id="game-42"
        ).project

    def _upload(self, data=GAME_V1, **kw):
        with defer_patch() as configure:
            result = upload_service.upload_version(self.project, data, uploaded_by="platform", **kw)
        return result, configure

    def test_an_upload_is_stored_and_checked_like_a_pushed_commit(self):
        result, configure = self._upload(label="1.0.0")

        version = result.version
        self.assertTrue(result.created)
        self.assertEqual(version.label, "1.0.0")
        self.assertEqual(version.channel, "main")
        self.assertEqual(version.file_count, 2)
        check = CommitCheck.objects.get(project=self.project)
        self.assertEqual(check.commit_sha, version.digest)
        self.assertEqual(check.branch, "main")
        self.assertEqual(check.event_type, "upload")
        self.assertEqual(result.run["queued"], 1)
        configure.return_value.defer.assert_called_once()

    def test_the_languages_come_from_the_uploaded_files(self):
        self._upload()
        self.project.refresh_from_db()
        self.assertEqual(sorted(self.project.languages), ["HTML", "JavaScript"])

    def test_the_same_bytes_again_are_the_same_version_but_checked_again(self):
        first, _ = self._upload()
        again, _ = self._upload()

        self.assertFalse(again.created)
        self.assertEqual(again.version.pk, first.version.pk)
        self.assertEqual(ProjectVersion.objects.count(), 1)
        self.assertEqual(CommitCheck.objects.filter(project=self.project).count(), 2)

    def test_a_channel_is_the_version_branch(self):
        result, _ = self._upload(channel="review")
        self.assertEqual(result.version.channel, "review")
        self.assertEqual(CommitCheck.objects.get().branch, "review")

    def test_only_standards_that_run_on_uploads_are_queued(self):
        push_only = baker.make("app.Standard", tenant=self.tenant, criteria={"events": ["push"]})
        self.project.standards.add(push_only)

        result, _ = self._upload()

        self.assertEqual(
            [e["standard_id"] for e in result.run["executions"]], [str(self.standard.pk)]
        )

    def test_a_rejected_archive_stores_nothing(self):
        with self.assertRaises(UploadRejected):
            self._upload(make_zip({"../escape.js": b"x"}))
        self.assertFalse(ProjectVersion.objects.exists())
        self.assertFalse(CommitCheck.objects.exists())

    def test_a_git_project_takes_no_uploads(self):
        git_project = baker.make("app.Project", tenant=self.tenant)
        with self.assertRaises(ValueError):
            upload_service.upload_version(git_project, GAME_V1)

    def test_a_manual_run_before_any_upload_queues_nothing(self):
        with defer_patch() as configure:
            self.assertIsNone(enqueue_manual_run(self.project, [self.standard]))
        configure.assert_not_called()


class RunOnVersionTests(TestCase):
    """The ``run_standards`` job on an upload project's version."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.standard = _upload_standard(self.tenant, code="CODE")
        self.project = upload_service.create_upload_project(
            self.tenant, name="Space Race", external_id="game-42"
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
            upload_service.upload_version(self.project, data, **kw)
        job = configure.return_value.defer.call_args.kwargs
        with self._runner():
            tasks.run_standards.func(**job)
        return StandardExecution.objects.filter(pk__in=job["execution_ids"])

    def test_the_sandbox_reads_the_version_files_mounted_from_disk(self):
        executions = self._upload_and_run(GAME_V1)

        self.assertEqual(executions.get().status, StandardExecution.Status.PASSED)
        seen = self.seen[0]
        self.assertEqual(seen["files"], ["game.js", "index.html"])
        self.assertEqual(seen["index"], "<html>v1</html>")
        self.assertEqual(seen["config"]["platform"], "upload")
        self.assertNotIn("access_token", seen["config"])
        self.assertEqual(seen["config"]["ref"], ProjectVersion.objects.get().digest)

    def test_the_extracted_files_are_removed_after_the_job(self):
        self._upload_and_run(GAME_V1)
        self.assertFalse(Path(self.seen[0]["dir"]).exists())

    def test_each_version_is_read_at_its_own_files(self):
        self._upload_and_run(GAME_V1)
        self._upload_and_run(GAME_V2)
        self.assertEqual([s["index"] for s in self.seen], ["<html>v1</html>", "<html>v2</html>"])

    def test_a_run_on_a_channel_with_no_version_is_an_error_not_a_crash(self):
        with defer_patch() as configure:
            upload_service.upload_version(self.project, GAME_V1)
        ProjectVersion.objects.all().delete()  # gone before the job ran
        job = configure.return_value.defer.call_args.kwargs
        with self._runner():
            tasks.run_standards.func(**job)

        execution = StandardExecution.objects.get()
        self.assertEqual(execution.status, StandardExecution.Status.ERROR)
        self.assertIn("No version of Space Race has been uploaded", execution.message)


class VersionHistoryTests(TestCase):
    """The project page's branch/commit history reads versions for uploads."""

    def setUp(self):
        tenant = baker.make("app.Tenant")
        _upload_standard(tenant)
        self.project = upload_service.create_upload_project(
            tenant, name="Space Race", external_id="game-42"
        ).project
        with defer_patch():
            self.v1 = upload_service.upload_version(self.project, GAME_V1, label="1.0", uploaded_by="platform").version
            self.v2 = upload_service.upload_version(self.project, GAME_V2, label="1.1", uploaded_by="platform").version
            upload_service.upload_version(self.project, make_zip({"x.js": b"x"}), channel="review")

    def test_channels_are_the_branches(self):
        self.assertEqual(branches(self.project), ["main", "review"])

    def test_versions_are_the_commits_newest_first(self):
        rows, has_more = branch_commits(self.project, "main")
        self.assertEqual([r.sha for r in rows], [self.v2.digest, self.v1.digest])
        self.assertEqual([r.title for r in rows], ["1.1", "1.0"])
        self.assertEqual(rows[0].author, "platform")
        self.assertFalse(has_more)

    def test_a_version_check_reports_through_the_commit_lookup(self):
        row = commit_results(self.project, self.v2.digest)
        self.assertTrue(row.checked)
        self.assertEqual(row.running, 1)  # queued, the worker has not run it yet
