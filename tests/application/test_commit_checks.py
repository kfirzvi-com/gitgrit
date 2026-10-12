"""Commit checks: runs are grouped per commit, pinned to it, and laid over a
branch's history."""
from datetime import timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from model_bakery import baker

from app.application import commit_checks
from app.application.commit_checks import (
    CommitRow,
    branch_commits,
    branches,
    pin_head_commits,
)
from app.application.standard_engine import StandardEngine
from app.application.standard_runs import enqueue_run
from app.domain.models import CommitCheck, StandardExecution
from tests.support import defer_patch

Status = StandardExecution.Status


def _project(**kwargs):
    tenant = baker.make("app.Tenant")
    return baker.make("app.Project", tenant=tenant, default_branch="main", **kwargs)


def _standard(project, name="Pinned CI", ref_filter=None):
    criteria = {"events": ["push"], "languages": []}
    if ref_filter:
        criteria["ref"] = ref_filter
    standard = baker.make(
        "app.Standard", tenant=project.tenant, name=name, enabled=True, draft=False, criteria=criteria
    )
    project.standards.add(standard)
    return standard


class EnqueueGroupsRunsTests(TestCase):
    def setUp(self):
        patch = defer_patch()
        patch.start()
        self.addCleanup(patch.stop)
        self.project = _project()

    def test_a_webhook_run_is_one_check_pinned_to_its_commit(self):
        standards = [_standard(self.project, "A"), _standard(self.project, "B")]

        enqueue_run(self.project, standards, event_type="push", ref="refs/heads/main", commit_sha="a" * 40, skip_running=False)

        check = CommitCheck.objects.get()
        self.assertEqual((check.branch, check.commit_sha, check.event_type), ("main", "a" * 40, "push"))
        self.assertEqual(check.executions.count(), 2)

    def test_a_manual_run_is_one_check_per_branch_it_reads_waiting_for_its_commit(self):
        _standard(self.project, "Default")
        _standard(self.project, "Develop only", ref_filter="^develop$")

        enqueue_run(self.project, self.project.standards.all())

        checks = {c.branch: c for c in CommitCheck.objects.all()}
        self.assertEqual(set(checks), {"main", "develop"})
        self.assertTrue(all(c.commit_sha == "" for c in checks.values()))
        self.assertEqual(checks["develop"].executions.get().standard_name, "Develop only")


class PinHeadCommitsTests(TestCase):
    def setUp(self):
        self.project = _project()
        self.standard = _standard(self.project)

    def _run(self, sha=""):
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha=sha)
        baker.make("app.StandardExecution", project=self.project, standard=self.standard, commit_check=check)
        return check

    def _executions(self):
        return StandardExecution.objects.select_related("commit_check")

    def test_an_unpinned_check_gets_its_branch_head(self):
        check = self._run()
        head = {"sha": "b" * 40, "date": "2026-10-02T09:00:00Z"}
        with mock.patch.object(commit_checks, "resolve_head_commit", return_value=head) as resolve:
            pin_head_commits(self.project, self._executions())

        resolve.assert_called_once_with(self.project, "main")
        check.refresh_from_db()
        self.assertEqual(check.commit_sha, "b" * 40)
        self.assertEqual(check.committed_at.isoformat(), "2026-10-02T09:00:00+00:00")

    def test_a_pinned_check_is_left_alone(self):
        check = self._run(sha="c" * 40)
        with mock.patch.object(commit_checks, "resolve_head_commit") as resolve:
            pin_head_commits(self.project, self._executions())

        resolve.assert_not_called()
        check.refresh_from_db()
        self.assertEqual(check.commit_sha, "c" * 40)

    def test_when_the_platform_cannot_say_the_check_stays_unpinned(self):
        check = self._run()
        with mock.patch.object(commit_checks, "_client", side_effect=RuntimeError("down")):
            pin_head_commits(self.project, self._executions())

        check.refresh_from_db()
        self.assertEqual(check.commit_sha, "")


class SandboxReadsThePinnedCommitTests(TestCase):
    def test_the_run_reads_the_checks_commit_not_the_branch(self):
        project = _project()
        standard = _standard(project)
        check = baker.make("app.CommitCheck", project=project, branch="main", commit_sha="d" * 40)
        execution = baker.make(
            "app.StandardExecution", project=project, standard=standard, ref="refs/heads/main",
            commit_check=check, status=Status.RUNNING,
        )
        with mock.patch("app.application.standard_engine.SandboxRunner") as runner_cls:
            runner = runner_cls.return_value
            runner.run.return_value = {"passed": True, "score": 100, "message": "ok", "details": {}}
            StandardEngine().run_execution(execution, {"full_path": project.full_path})

        _, config = runner.run.call_args.args
        self.assertEqual(config["ref"], "d" * 40)

    def test_an_unpinned_run_reads_its_branch(self):
        project = _project()
        standard = _standard(project)
        execution = baker.make(
            "app.StandardExecution", project=project, standard=standard, ref="refs/heads/develop",
            status=Status.RUNNING,
        )
        with mock.patch("app.application.standard_engine.SandboxRunner") as runner_cls:
            runner = runner_cls.return_value
            runner.run.return_value = {"passed": True, "score": 100, "message": "ok", "details": {}}
            StandardEngine().run_execution(execution, {})

        _, config = runner.run.call_args.args
        self.assertEqual(config["ref"], "develop")


class BranchHistoryTests(TestCase):
    def setUp(self):
        self.project = _project()
        self.client_mock = mock.Mock()
        patch = mock.patch.object(commit_checks, "_client", return_value=self.client_mock)
        patch.start()
        self.addCleanup(patch.stop)

    def _commit(self, sha, message="Do a thing\n\nmore", date="2026-10-01T10:00:00Z"):
        return {"sha": sha, "message": message, "author": "Dana", "date": date, "url": f"https://x/{sha}"}

    def _result(self, sha, standard, status, score, ago=None):
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha=sha)
        ex = baker.make(
            "app.StandardExecution", project=self.project, standard=standard, standard_name=standard.name,
            status=status, score=score, commit_check=check,
        )
        if ago:
            StandardExecution.objects.filter(pk=ex.pk).update(created_at=timezone.now() - ago)
        return ex

    def test_branches_put_the_default_first_then_the_rest_sorted(self):
        self.client_mock.list_branches.return_value = ["zeta", "main", "alpha"]
        self.assertEqual(branches(self.project), ["main", "alpha", "zeta"])

    def test_branches_fall_back_to_checked_branches(self):
        self.client_mock.list_branches.side_effect = RuntimeError("down")
        baker.make("app.CommitCheck", project=self.project, branch="feature/x", commit_sha="e" * 40)
        self.assertEqual(branches(self.project), ["main", "feature/x"])

    def test_commits_carry_the_latest_result_of_each_standard(self):
        a, b = _standard(self.project, "A"), _standard(self.project, "B")
        self.client_mock.list_commits.return_value = [self._commit("1" * 40), self._commit("2" * 40)]
        self._result("1" * 40, a, Status.FAILED, 0, ago=timedelta(hours=1))
        self._result("1" * 40, a, Status.PASSED, 100)
        self._result("1" * 40, b, Status.ERROR, 0)

        rows, has_more = branch_commits(self.project, "main")

        checked, unchecked = rows
        self.assertEqual((checked.short_sha, checked.title, checked.author), ("1111111", "Do a thing", "Dana"))
        self.assertEqual((checked.passed, checked.failed, checked.errored), (1, 0, 1))
        self.assertEqual(checked.score, 50)
        self.assertFalse(unchecked.checked)
        self.assertFalse(has_more)

    def test_a_full_page_means_there_are_older_commits(self):
        self.client_mock.list_commits.return_value = [
            self._commit(f"{i:040d}") for i in range(commit_checks.COMMITS_PER_PAGE)
        ]
        _, has_more = branch_commits(self.project, "main")
        self.assertTrue(has_more)

    def test_commits_fall_back_to_checked_commits(self):
        a = _standard(self.project, "A")
        self.client_mock.list_commits.side_effect = RuntimeError("down")
        self._result("3" * 40, a, Status.PASSED, 100)

        rows, _ = branch_commits(self.project, "main")

        self.assertEqual([r.sha for r in rows], ["3" * 40])
        self.assertTrue(rows[0].checked)


class CommitRowTests(SimpleTestCase):
    def test_a_running_result_does_not_move_the_score(self):
        row = CommitRow(sha="f" * 40, results=[
            mock.Mock(status=Status.PASSED, score=100),
            mock.Mock(status=Status.RUNNING, score=0),
        ])
        self.assertEqual((row.running, row.score), (1, 100))

    def test_an_unchecked_commit(self):
        row = CommitRow(sha="f" * 40)
        self.assertFalse(row.checked)
        self.assertIsNone(row.score)
        self.assertEqual(row.title, "")


class VersionSnapshotTests(TestCase):
    """Every run records the version of the standard it ran, and runs it."""

    def setUp(self):
        patch = defer_patch()
        patch.start()
        self.addCleanup(patch.stop)
        self.project = _project()
        self.standard = _standard(self.project)

    def _queue(self):
        enqueue_run(self.project, [self.standard], skip_running=False)
        return StandardExecution.objects.order_by("-created_at").first()

    def test_a_standard_with_no_version_gets_a_snapshot(self):
        execution = self._queue()
        self.assertEqual(execution.standard_version.version, 1)
        self.assertEqual(execution.standard_version.code, self.standard.code)

    def test_an_unchanged_standard_reuses_its_latest_version(self):
        first = self._queue()
        second = self._queue()
        self.assertEqual(first.standard_version_id, second.standard_version_id)

    def test_a_changed_standard_gets_a_new_snapshot(self):
        first = self._queue()
        self.standard.code = "def evaluate(project):\n    return {'passed': True}\n"
        self.standard.save()
        second = self._queue()
        self.assertEqual((first.standard_version.version, second.standard_version.version), (1, 2))

    def test_the_sandbox_runs_the_snapshot_not_the_edited_standard(self):
        execution = self._queue()
        snapshot_code = execution.standard_version.code
        self.standard.code = "edited after queueing"
        self.standard.save()
        execution.refresh_from_db()
        with mock.patch("app.application.standard_engine.SandboxRunner") as runner_cls:
            runner = runner_cls.return_value
            runner.run.return_value = {"passed": True, "score": 100, "message": "ok", "details": {}}
            StandardEngine().run_execution(execution, {})
        self.assertEqual(runner.run.call_args.args[0], snapshot_code)


class NewestCommitWinsTests(TestCase):
    """A branch's current results come from its newest commit, so checking an
    old commit again does not change its health."""

    def test_rerunning_an_old_commit_does_not_take_over(self):
        from app.application.standard_results import current_results

        project = _project()
        standard = _standard(project)
        now = timezone.now()
        new = baker.make("app.CommitCheck", project=project, branch="main", commit_sha="1" * 40, committed_at=now)
        old = baker.make("app.CommitCheck", project=project, branch="main", commit_sha="2" * 40,
                         committed_at=now - timedelta(days=3))
        newest_commit = baker.make("app.StandardExecution", project=project, standard=standard,
                                   status=Status.PASSED, score=100, commit_check=new, ref="")
        rerun = baker.make("app.StandardExecution", project=project, standard=standard,
                           status=Status.FAILED, score=0, commit_check=old, ref="")
        StandardExecution.objects.filter(pk=newest_commit.pk).update(created_at=now - timedelta(hours=1))

        self.assertEqual([r.pk for r in current_results([project])], [newest_commit.pk])
        self.assertTrue(rerun.created_at > newest_commit.created_at - timedelta(hours=1))


class AttachmentsChangeOverTimeTests(TestCase):
    def setUp(self):
        self.project = _project()
        self.client_mock = mock.Mock()
        patch = mock.patch.object(commit_checks, "_client", return_value=self.client_mock)
        patch.start()
        self.addCleanup(patch.stop)
        self.client_mock.list_commits.return_value = [
            {"sha": "a" * 40, "message": "m", "author": "", "date": "", "url": ""}
        ]

    def test_a_commit_lists_current_standards_that_did_not_run_on_it(self):
        ran = _standard(self.project, "Ran then")
        _standard(self.project, "Attached since")
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha="a" * 40)
        baker.make("app.StandardExecution", project=self.project, standard=ran, status=Status.PASSED, commit_check=check)

        [row], _ = branch_commits(self.project, "main")

        self.assertEqual([s.name for s in row.not_run], ["Attached since"])
        self.assertTrue(row.results[0].still_attached)

    def test_a_result_of_a_detached_standard_says_so(self):
        detached = _standard(self.project, "Detached since")
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha="a" * 40)
        baker.make("app.StandardExecution", project=self.project, standard=detached, status=Status.FAILED, commit_check=check)
        self.project.standards.remove(detached)

        [row], _ = branch_commits(self.project, "main")

        self.assertFalse(row.results[0].still_attached)
        self.assertEqual(row.not_run, [])


class StandardsForBranchTests(TestCase):
    def test_only_standards_whose_filter_matches_the_branch(self):
        project = _project()
        _standard(project, "Everywhere")
        _standard(project, "Develop only", ref_filter="^develop$")
        names = lambda branch: sorted(s.name for s in StandardEngine().standards_for_branch(project, branch))
        self.assertEqual(names("main"), ["Everywhere"])
        self.assertEqual(names("develop"), ["Develop only", "Everywhere"])
