"""Grade alerts, part A: the ``gitgrit/grade`` commit status.

``grade_status_line`` maps a project status dict to a commit status; the
``run_standards`` job posts it once after a normal run — to the event's
commit, or to the default branch head when the run had none (manual, attach,
save, activate). The GitHub client is mocked throughout
(``get_platform_client`` in ``grade_alerts``).
"""
from unittest import mock

import pytest
from django.test import SimpleTestCase, TestCase, override_settings
from model_bakery import baker

from app import tasks
from app.application import grade_alerts
from app.application.standard_runs import enqueue_for_event, enqueue_run
from app.domain.events import DomainEvent
from app.domain.models import StandardExecution
from tests.support import defer_patch

SHA = "c" * 40
HEAD = "d" * 40
PASSED = {"passed": True, "score": 100, "message": "OK", "details": {}}
FAILED = {"passed": False, "score": 10, "message": "nope", "details": {}}


def _status(grade, score, passed, failed, worst="secrets-in-repo"):
    return {
        "grade": grade,
        "overall_score": score,
        "total_standards": passed + failed,
        "passed": passed,
        "failed": failed,
        "top_offenders": [{"name": worst, "score": 0}] if passed + failed else [],
    }


class GradeStatusLineTests(SimpleTestCase):
    def test_grade_to_state(self):
        cases = [
            ("excellent", "success"),
            ("good", "success"),
            ("warning", "failure"),
            ("critical", "failure"),
        ]
        for grade, state in cases:
            with self.subTest(grade=grade):
                assert grade_alerts.grade_status_line(_status(grade, 50, 1, 1))[0] == state

    def test_description_names_the_worst_failing_standard(self):
        _, description = grade_alerts.grade_status_line(_status("warning", 62.2, 5, 4))
        assert description == "Grade warning · 62/100 · 5/9 passed · worst: secrets-in-repo"

    def test_description_omits_worst_when_everything_passed(self):
        _, description = grade_alerts.grade_status_line(_status("excellent", 100, 3, 0))
        assert description == "Grade excellent · 100/100 · 3/3 passed"

    def test_unknown_grade_is_not_a_status(self):
        with pytest.raises(KeyError):
            grade_alerts.grade_status_line(_status("unknown", None, 0, 0))


@pytest.mark.django_db
class EnqueueForwardsCommitShaTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.connection = baker.make(
            "app.PlatformConnection", tenant=self.tenant, platform="github", access_token="t"
        )
        self.project = baker.make(
            "app.Project",
            tenant=self.tenant,
            platform="github",
            platform_connection=self.connection,
            external_id="42",
            full_path="acme/repo",
            languages=[],
        )
        self.standard = baker.make(
            "app.Standard",
            tenant=self.tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["push"], "ref": "", "languages": []},
        )
        self.project.standards.add(self.standard)

    def test_webhook_event_sha_reaches_the_job(self):
        event = DomainEvent(
            event_type="push",
            platform="github",
            external_project_id="42",
            ref="refs/heads/main",
            commit_sha=SHA,
            actor="alice",
        )
        with defer_patch() as configure:
            enqueue_for_event(event)
        kwargs = configure.return_value.defer.call_args.kwargs
        assert kwargs["commit_sha"] == SHA

    def test_manual_run_passes_no_sha(self):
        with defer_patch() as configure:
            enqueue_run(self.project, [self.standard])
        assert configure.return_value.defer.call_args.kwargs["commit_sha"] is None


@pytest.mark.django_db
@override_settings(SITE_URL="https://app.example.test/")
class RunStandardsPostsCommitStatusTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make(
            "app.Project",
            tenant=self.tenant,
            platform="github",
            full_path="acme/repo",
            default_branch="main",
        )
        self.client_mock = mock.Mock()
        self.client_mock.get_branch_head.return_value = HEAD
        patcher = mock.patch(
            "app.application.grade_alerts.get_platform_client",
            return_value=self.client_mock,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _execution(self, code):
        standard = baker.make("app.Standard", tenant=self.tenant, code=code)
        self.project.standards.add(standard)
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            event_type="push",
            status=StandardExecution.Status.RUNNING,
        )

    def _run(self, executions, commit_sha, results):
        runner = mock.Mock()
        runner.run.side_effect = results
        with mock.patch(
            "app.application.standard_engine.SandboxRunner", return_value=runner
        ), mock.patch(
            "app.application.standard_engine.StandardEngine.build_input_config",
            return_value={},
        ):
            tasks.run_standards.func(
                project_id=str(self.project.pk),
                execution_ids=[str(e.pk) for e in executions],
                commit_sha=commit_sha,
            )

    def test_posts_the_grade_once_after_the_run(self):
        ok = self._execution("A")
        bad = self._execution("B")

        self._run([ok, bad], SHA, [dict(PASSED), dict(FAILED)])

        self.client_mock.set_commit_status.assert_called_once()
        full_path, sha, state, description, target_url = (
            self.client_mock.set_commit_status.call_args.args
        )
        assert (full_path, sha, state) == ("acme/repo", SHA, "failure")
        assert description == (
            f"Grade warning · 55/100 · 1/2 passed · worst: {bad.standard_name}"
        )
        assert target_url == f"https://app.example.test/projects/{self.project.pk}/"

    def test_event_commit_is_used_without_a_lookup(self):
        self._run([self._execution("A")], SHA, [dict(PASSED)])
        self.client_mock.get_branch_head.assert_not_called()
        assert self.client_mock.set_commit_status.call_args.args[1] == SHA

    def test_run_without_a_commit_posts_to_the_default_branch_head(self):
        # Manual runs and attach/save/activate runs have no event commit.
        self._run([self._execution("A")], None, [dict(PASSED)])

        self.client_mock.get_branch_head.assert_called_once_with("acme/repo", "main")
        self.client_mock.set_commit_status.assert_called_once()
        assert self.client_mock.set_commit_status.call_args.args[1] == HEAD

    def test_unresolved_head_posts_nothing(self):
        self.client_mock.get_branch_head.return_value = None
        self._run([self._execution("A")], None, [dict(PASSED)])
        self.client_mock.set_commit_status.assert_not_called()

    def test_unknown_grade_posts_nothing(self):
        # A run whose only row errored leaves no PASSED/FAILED result to grade.
        gone = self._execution("A")
        gone.standard.delete()
        self._run([gone], SHA, [])
        self.client_mock.set_commit_status.assert_not_called()

    def test_raising_runner_posts_nothing(self):
        with pytest.raises(RuntimeError):
            self._run([self._execution("A")], SHA, RuntimeError("sandbox exploded"))
        self.client_mock.set_commit_status.assert_not_called()

    def test_raising_client_does_not_fail_the_job(self):
        self.client_mock.set_commit_status.side_effect = RuntimeError("403 Forbidden")
        row = self._execution("A")

        with self.assertLogs("app.application.grade_alerts", level="WARNING") as logs:
            self._run([row], SHA, [dict(PASSED)])

        row.refresh_from_db()
        assert row.status == StandardExecution.Status.PASSED
        assert "could not post commit status" in logs.output[0]
