"""The branch a standard runs for, and the branch it reads the repository at.

The Branch/Tag Filter matches the branch an event is *for*: the pushed branch,
or a pull request's target branch. Empty means the default branch only.
Webhook runs read at the pushed branch / the PR's source branch; manual runs
(project page, connect-to-project) read at the branch the filter names
literally, else the default branch. The sandbox is mocked; we assert on
/input.json.
"""
from unittest import mock

import pytest
from model_bakery import baker

from app.application.standard_engine import StandardEngine, bare_ref, literal_ref
from app.domain.events import DomainEvent


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("", ""),
        (None, ""),
        ("main", "main"),
        ("^main$", "main"),
        ("release/1.0", "release/1.0"),
        ("v1.2.3", "v1.2.3"),
        ("^release/.*", ""),
        ("^v\\d+\\.", ""),
        ("main|develop", ""),
    ],
)
def test_literal_ref(pattern, expected):
    assert literal_ref(pattern) == expected


def test_bare_ref_strips_webhook_prefix():
    assert bare_ref("refs/heads/feature/x") == "feature/x"
    assert bare_ref("refs/tags/v1.0") == "v1.0"
    assert bare_ref("develop") == "develop"
    assert bare_ref(None) == ""


def _passed():
    return {"passed": True, "score": 100, "message": "ok", "details": {}}


@pytest.mark.django_db
class TestRunRef:
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

    def _engine(self):
        engine = StandardEngine()
        engine._runner = mock.Mock()
        engine._runner.run.return_value = _passed()
        return engine

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
        engine = self._engine()

        engine.run_for_project(project)

        _, input_config = engine._runner.run.call_args.args
        assert input_config["ref"] == "develop"
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
        engine = self._engine()

        engine.run_for_project(project)

        _, input_config = engine._runner.run.call_args.args
        assert input_config["ref"] == ""

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
        engine = self._engine()
        event = DomainEvent(
            event_type="push",
            platform="github",
            external_project_id="42",
            ref="refs/heads/develop",
            actor="alice",
            raw_payload={},
        )

        results = engine.run_for_event(event)

        assert len(results) == 1
        _, input_config = engine._runner.run.call_args.args
        assert input_config["ref"] == "develop"

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
        engine = self._engine()
        event = DomainEvent(
            event_type="push",
            platform="github",
            external_project_id="42",
            ref="refs/heads/main",
            actor="alice",
            raw_payload={},
        )

        assert engine.run_for_event(event) == []
        engine._runner.run.assert_not_called()

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
        engine = self._engine()

        results = engine.run_for_event(self._pull_request("feature/x", "gritest"))

        assert len(results) == 1
        _, input_config = engine._runner.run.call_args.args
        assert input_config["ref"] == "feature/x"
        assert project.standard_executions.get().ref == "feature/x"

    def test_pull_request_from_filtered_branch_into_other_does_not_run(self):
        project = self._project()
        self._standard(project, "^gritest$")
        engine = self._engine()

        assert engine.run_for_event(self._pull_request("gritest", "main")) == []
        engine._runner.run.assert_not_called()

    def test_empty_filter_runs_on_push_to_default_branch(self):
        project = self._project()
        self._standard(project, "")
        engine = self._engine()

        results = engine.run_for_event(self._push("refs/heads/main"))

        assert len(results) == 1
        _, input_config = engine._runner.run.call_args.args
        assert input_config["ref"] == "main"

    def test_empty_filter_skips_push_to_other_branch(self):
        project = self._project()
        self._standard(project, "")
        engine = self._engine()

        assert engine.run_for_event(self._push("refs/heads/feature/x")) == []
        engine._runner.run.assert_not_called()

    def test_empty_filter_runs_on_pull_request_into_default_branch(self):
        project = self._project()
        self._standard(project, "")
        engine = self._engine()

        results = engine.run_for_event(self._pull_request("feature/x", "main"))

        assert len(results) == 1
        _, input_config = engine._runner.run.call_args.args
        assert input_config["ref"] == "feature/x"

    def test_empty_filter_skips_pull_request_into_other_branch(self):
        project = self._project()
        self._standard(project, "")
        engine = self._engine()

        assert engine.run_for_event(self._pull_request("feature/x", "gritest")) == []
        engine._runner.run.assert_not_called()

    def test_event_without_ref_skips_filter(self):
        project = self._project()
        self._standard(project, "")
        engine = self._engine()

        results = engine.run_for_event(self._push(None))

        assert len(results) == 1
        _, input_config = engine._runner.run.call_args.args
        assert input_config["ref"] == ""
