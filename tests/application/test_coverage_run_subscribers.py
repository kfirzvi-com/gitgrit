"""Coverage-change subscribers: attach/save/activate events run the delta.

Unit tests of the handlers in ``app.application.subscribers`` — the engine's
``run_for_project`` is mocked (no sandbox), while the runnable/criteria
filtering runs for real.
"""
from unittest import mock

import pytest
from django.test import TestCase
from model_bakery import baker

from app.application import subscribers
from app.domain.events import StandardsAttached, StandardSaved

PASSED = {"passed": True, "score": 100, "message": "OK", "details": {}}
FAILED = {"passed": False, "score": 0, "message": "nope", "details": {}}
ERRORED = {"passed": False, "score": 0, "message": "boom", "details": {"error": "boom"}}


def _run_patch(results):
    return mock.patch(
        "app.application.standard_engine.StandardEngine.run_for_project",
        return_value=results,
    )


def _attached_event(project, standards):
    return StandardsAttached(
        project_id=str(project.pk),
        tenant_id=str(project.tenant_id),
        standard_ids=tuple(str(s.pk) for s in standards),
    )


@pytest.mark.django_db
class StandardsAttachedTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant)

    def test_runs_only_runnable_standards(self):
        runnable = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)
        draft = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=True)
        disabled = baker.make("app.Standard", tenant=self.tenant, enabled=False, draft=False)

        with _run_patch([PASSED]) as run:
            summary = subscribers._on_standards_attached(
                _attached_event(self.project, [runnable, draft, disabled])
            )

        run.assert_called_once()
        project_arg, standards_arg = run.call_args[0]
        assert project_arg == self.project
        assert standards_arg == [runnable]
        assert summary["ran"] == 1
        assert summary["passed"] == 1

    def test_criteria_language_mismatch_is_filtered(self):
        self.project.languages = ["python"]
        self.project.save(update_fields=["languages"])
        mismatched = baker.make(
            "app.Standard", tenant=self.tenant, criteria={"languages": ["go"]}
        )

        with _run_patch([PASSED]) as run:
            summary = subscribers._on_standards_attached(
                _attached_event(self.project, [mismatched])
            )

        run.assert_not_called()
        assert summary is None

    def test_deleted_project_is_a_noop(self):
        standard = baker.make("app.Standard", tenant=self.tenant)
        event = _attached_event(self.project, [standard])
        self.project.delete()

        with _run_patch([PASSED]) as run:
            assert subscribers._on_standards_attached(event) is None
        run.assert_not_called()

    def test_summary_counts_passed_failed_and_errors(self):
        standards = baker.make("app.Standard", tenant=self.tenant, _quantity=3)

        with _run_patch([PASSED, FAILED, ERRORED]):
            summary = subscribers._on_standards_attached(
                _attached_event(self.project, standards)
            )

        assert summary == {
            "projects": 1,
            "ran": 3,
            "passed": 1,
            "failed": 1,
            "errors": 1,
            "message": "Ran 3 standards on 1 project: 1 passed, 1 failed, 1 errored.",
        }

    def test_error_takes_precedence_over_passed(self):
        # details is standard-author-controlled: a result claiming both
        # passed and an error must land in exactly one bucket.
        standard = baker.make("app.Standard", tenant=self.tenant)
        ambiguous = {"passed": True, "score": 100, "message": "?", "details": {"error": "x"}}

        with _run_patch([ambiguous]):
            summary = subscribers._on_standards_attached(
                _attached_event(self.project, [standard])
            )

        assert summary["ran"] == 1
        assert summary["passed"] == 0
        assert summary["errors"] == 1
        assert summary["failed"] == 0


@pytest.mark.django_db
class StandardChangedTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.standard = baker.make("app.Standard", tenant=self.tenant)

    def _event(self):
        return StandardSaved(
            standard_id=str(self.standard.pk), tenant_id=str(self.tenant.pk)
        )

    def test_runs_on_every_linked_project_only(self):
        linked_a = baker.make("app.Project", tenant=self.tenant)
        linked_b = baker.make("app.Project", tenant=self.tenant)
        baker.make("app.Project", tenant=self.tenant)  # not linked
        linked_a.standards.add(self.standard)
        linked_b.standards.add(self.standard)

        with _run_patch([PASSED]) as run:
            summary = subscribers._on_standard_changed(self._event())

        assert run.call_count == 2
        ran_on = {call.args[0] for call in run.call_args_list}
        assert ran_on == {linked_a, linked_b}
        assert all(call.args[1] == [self.standard] for call in run.call_args_list)
        assert summary["projects"] == 2
        assert summary["ran"] == 2

    def test_no_linked_projects_is_a_noop(self):
        with _run_patch([PASSED]) as run:
            assert subscribers._on_standard_changed(self._event()) is None
        run.assert_not_called()

    def test_deleted_standard_is_a_noop(self):
        event = self._event()
        self.standard.delete()

        with _run_patch([PASSED]) as run:
            assert subscribers._on_standard_changed(event) is None
        run.assert_not_called()
