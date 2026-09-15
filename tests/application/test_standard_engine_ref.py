"""The branch a standard runs for, and the branch it reads the repository at.

The Branch/Tag Filter matches the branch an event is *for*: the pushed branch,
or a pull request's target branch. Empty matches all branches and tags.
Webhook runs read at the pushed branch / the PR's source branch; manual runs
(project page, connect-to-project) read at the branch the filter names
literally, else the default branch. Runs are queued and executed by the
``run_standards`` job; here the job runs inline and the sandbox is mocked, so
we assert on the /input.json it receives and the ref recorded on the execution.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase
from model_bakery import baker

from app.application.standard_engine import bare_ref, literal_ref
from app.application.standard_runs import enqueue_for_event, enqueue_manual_run
from app.domain.events import DomainEvent
from tests.support import queued_standards_run_inline


class TestRefHelpers(SimpleTestCase):
    def test_literal_ref(self):
        cases = [
            ("", ""),
            (None, ""),
            ("main", "main"),
            ("^main$", "main"),
            ("release/1.0", "release/1.0"),
            ("v1.2.3", "v1.2.3"),
            ("^release/.*", ""),
            ("^v\\d+\\.", ""),
            ("main|develop", ""),
        ]
        for pattern, expected in cases:
            with self.subTest(pattern=pattern):
                assert literal_ref(pattern) == expected

    def test_bare_ref_strips_webhook_prefix(self):
        assert bare_ref("refs/heads/feature/x") == "feature/x"
        assert bare_ref("refs/tags/v1.0") == "v1.0"
        assert bare_ref("develop") == "develop"
        assert bare_ref(None) == ""


def _passed():
    return {"passed": True, "score": 100, "message": "ok", "details": {}}


class TestRunRef(TestCase):
    def _project(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            access_token="tok",
        )
        return baker.make(
            "app.Project",
            tenant=tenant,
            platform="github",
            platform_connection=connection,
            external_id="42",
            full_path="acme/repo",
            default_branch="main",
            languages=[],
        )

    def setUp(self):
        """The job runs inline; the sandbox is a mock that records its input."""
        runner_patch = mock.patch("app.application.standard_engine.SandboxRunner")
        self.runner = runner_patch.start().return_value
        self.addCleanup(runner_patch.stop)
        self.runner.run.side_effect = lambda code, cfg: _passed()
        inline = queued_standards_run_inline()
        inline.__enter__()
        self.addCleanup(inline.__exit__, None, None, None)

    def _sandbox_ref(self):
        _, input_config = self.runner.run.call_args.args
        return input_config["ref"]

    def _manual_run(self, project):
        return enqueue_manual_run(project, project.standards.all())

    def _webhook_run(self, event):
        return enqueue_for_event(event)

    def test_manual_run_reads_at_filter_branch(self):
        project = self._project()
        standard = baker.make(
            "app.Standard",
            tenant=project.tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["push"], "ref": "^develop$", "languages": []},
        )
        project.standards.add(standard)

        self._manual_run(project)

        assert self._sandbox_ref() == "develop"
        assert project.standard_executions.get().ref == "develop"

    def test_manual_run_with_regex_filter_reads_default_branch(self):
        project = self._project()
        standard = baker.make(
            "app.Standard",
            tenant=project.tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["push"], "ref": "^release/.*", "languages": []},
        )
        project.standards.add(standard)

        self._manual_run(project)

        assert self._sandbox_ref() == ""

    def test_webhook_run_reads_at_event_branch(self):
        project = self._project()
        standard = baker.make(
            "app.Standard",
            tenant=project.tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["push"], "ref": "^develop$", "languages": []},
        )
        project.standards.add(standard)
        event = DomainEvent(
            event_type="push",
            platform="github",
            external_project_id="42",
            ref="refs/heads/develop",
            actor="alice",
            raw_payload={},
        )

        queued = self._webhook_run(event)

        assert len(queued) == 1
        assert self._sandbox_ref() == "develop"

    def test_webhook_on_other_branch_does_not_run(self):
        project = self._project()
        standard = baker.make(
            "app.Standard",
            tenant=project.tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["push"], "ref": "^develop$", "languages": []},
        )
        project.standards.add(standard)
        event = DomainEvent(
            event_type="push",
            platform="github",
            external_project_id="42",
            ref="refs/heads/main",
            actor="alice",
            raw_payload={},
        )

        assert self._webhook_run(event) == []
        self.runner.run.assert_not_called()

    def _standard(self, project, ref_pattern, events=("push", "pull_request")):
        standard = baker.make(
            "app.Standard",
            tenant=project.tenant,
            enabled=True,
            draft=False,
            criteria={"events": list(events), "ref": ref_pattern, "languages": []},
        )
        project.standards.add(standard)
        return standard

    def _pull_request(self, source, target):
        return DomainEvent(
            event_type="pull_request",
            platform="github",
            external_project_id="42",
            ref=source,
            target_ref=target,
            actor="alice",
            raw_payload={},
        )

    def _push(self, ref):
        return DomainEvent(
            event_type="push",
            platform="github",
            external_project_id="42",
            ref=ref,
            actor="alice",
            raw_payload={},
        )

    def test_pull_request_filter_matches_target_and_reads_source(self):
        project = self._project()
        self._standard(project, "gritest")

        queued = self._webhook_run(self._pull_request("feature/x", "gritest"))

        assert len(queued) == 1
        assert self._sandbox_ref() == "feature/x"
        assert project.standard_executions.get().ref == "feature/x"

    def test_pull_request_from_filtered_branch_into_other_does_not_run(self):
        project = self._project()
        self._standard(project, "^gritest$")

        assert self._webhook_run(self._pull_request("gritest", "main")) == []
        self.runner.run.assert_not_called()

    def test_empty_filter_runs_on_push_to_default_branch(self):
        project = self._project()
        self._standard(project, "")

        queued = self._webhook_run(self._push("refs/heads/main"))

        assert len(queued) == 1
        assert self._sandbox_ref() == "main"

    def test_empty_filter_runs_on_push_to_other_branch(self):
        project = self._project()
        self._standard(project, "")

        queued = self._webhook_run(self._push("refs/heads/feature/x"))

        assert len(queued) == 1
        assert self._sandbox_ref() == "feature/x"

    def test_empty_filter_runs_on_pull_request_into_default_branch(self):
        project = self._project()
        self._standard(project, "")

        queued = self._webhook_run(self._pull_request("feature/x", "main"))

        assert len(queued) == 1
        assert self._sandbox_ref() == "feature/x"

    def test_empty_filter_runs_on_pull_request_into_other_branch(self):
        project = self._project()
        self._standard(project, "")

        queued = self._webhook_run(self._pull_request("feature/x", "gritest"))

        assert len(queued) == 1
        assert self._sandbox_ref() == "feature/x"

    def test_event_without_ref_skips_filter(self):
        project = self._project()
        self._standard(project, "")

        queued = self._webhook_run(self._push(None))

        assert len(queued) == 1
        assert self._sandbox_ref() == ""

    def test_second_push_while_first_is_running_is_not_dropped(self):
        # Webhook runs never skip: each event gets its own execution, and the
        # per-project job lock serializes them. Here the job runs inline, so
        # the first is already finished; the point is that two pushes make
        # two executions rather than one.
        project = self._project()
        self._standard(project, "")

        self._webhook_run(self._push("refs/heads/main"))
        self._webhook_run(self._push("refs/heads/main"))

        assert project.standard_executions.count() == 2
        assert self.runner.run.call_count == 2
