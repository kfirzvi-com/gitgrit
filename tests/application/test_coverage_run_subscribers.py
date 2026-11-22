"""Coverage-change subscribers: attach/save/activate queue the delta.

Unit tests of the handlers in ``app.application.subscribers`` — the background
job's ``defer`` is mocked (nothing is enqueued, no sandbox), while the
runnable/criteria filtering and the RUNNING row creation run for real.
"""
from unittest import mock

import pytest
from django.test import TestCase
from model_bakery import baker

from app.application import scoring, subscribers
from app.domain.events import StandardActivated, StandardsAttached, StandardSaved
from app.domain.models import StandardExecution
from tests.support import defer_patch, running_executions



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

    def test_queues_only_runnable_standards(self):
        runnable = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)
        baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=True)
        baker.make("app.Standard", tenant=self.tenant, enabled=False, draft=False)
        standards = list(self.tenant.standards.all())
        self.project.standards.add(*standards)

        with defer_patch() as configure:
            summary = subscribers._on_standards_attached(
                _attached_event(self.project, standards)
            )

        rows = list(running_executions(self.project))
        assert [r.standard_id for r in rows] == [runnable.pk]
        assert rows[0].triggered_by == "attached"
        configure.assert_called_once_with(lock=f"standards:{self.project.pk}")
        configure.return_value.defer.assert_called_once_with(
            project_id=str(self.project.pk), execution_ids=[str(rows[0].pk)]
        )
        assert summary["queued"] == 1
        assert summary["projects"] == 1

    def test_attaching_one_standard_runs_every_attached_standard_so_the_commit_gets_a_score(self):
        # The new check expects every attached standard; running only the new
        # one left the others "not run" and the project score in error.
        existing = baker.make("app.Standard", tenant=self.tenant)
        new = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(existing, new)

        with defer_patch():
            subscribers._on_standards_attached(_attached_event(self.project, [new]))

        rows = list(running_executions(self.project))
        assert {r.standard_id for r in rows} == {existing.pk, new.pk}
        check = rows[0].commit_check
        assert {r.commit_check_id for r in rows} == {check.pk}

        check.commit_sha = "abc123"
        check.save(update_fields=["commit_sha"])
        running_executions(self.project).update(status=StandardExecution.Status.PASSED, score=80)
        commit_score = scoring.score_check(check)
        assert commit_score.value == 80
        assert commit_score.reason == ""

    def test_criteria_language_mismatch_is_filtered(self):
        self.project.languages = ["python"]
        self.project.save(update_fields=["languages"])
        mismatched = baker.make(
            "app.Standard", tenant=self.tenant, criteria={"languages": ["go"]}
        )
        self.project.standards.add(mismatched)

        with defer_patch() as configure:
            summary = subscribers._on_standards_attached(
                _attached_event(self.project, [mismatched])
            )

        configure.assert_not_called()
        assert not running_executions().exists()
        assert summary is None

    def test_deleted_project_is_a_noop(self):
        standard = baker.make("app.Standard", tenant=self.tenant)
        event = _attached_event(self.project, [standard])
        self.project.delete()

        with defer_patch() as configure:
            assert subscribers._on_standards_attached(event) is None
        configure.assert_not_called()

    def test_summary_message_reports_the_queued_count(self):
        standards = baker.make("app.Standard", tenant=self.tenant, _quantity=3)
        self.project.standards.add(*standards)

        with defer_patch():
            summary = subscribers._on_standards_attached(
                _attached_event(self.project, standards)
            )

        assert summary == {
            "projects": 1,
            "queued": 3,
            "already_running": 0,
            "message": (
                "Queued 3 standards on 1 project. "
                "Results appear on the project page as they finish."
            ),
        }
        assert running_executions(self.project).count() == 3

    def test_standards_already_running_are_reported_not_requeued(self):
        busy = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(busy)
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=busy,
            status=StandardExecution.Status.RUNNING,
        )

        with defer_patch() as configure:
            summary = subscribers._on_standards_attached(
                _attached_event(self.project, [busy])
            )

        configure.assert_not_called()
        assert running_executions(self.project).count() == 1
        assert summary["queued"] == 0
        assert summary["already_running"] == 1
        assert "1 already running" in summary["message"]


@pytest.mark.django_db
class StandardChangedTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.standard = baker.make("app.Standard", tenant=self.tenant)

    def _saved(self):
        return StandardSaved(
            standard_id=str(self.standard.pk), tenant_id=str(self.tenant.pk)
        )

    def _activated(self):
        return StandardActivated(
            standard_id=str(self.standard.pk), tenant_id=str(self.tenant.pk)
        )

    def test_queues_on_every_linked_project_only(self):
        linked_a = baker.make("app.Project", tenant=self.tenant)
        linked_b = baker.make("app.Project", tenant=self.tenant)
        unlinked = baker.make("app.Project", tenant=self.tenant)
        linked_a.standards.add(self.standard)
        linked_b.standards.add(self.standard)

        with defer_patch() as configure:
            summary = subscribers._on_standard_changed(self._saved())

        assert configure.call_count == 2
        assert {c.kwargs["lock"] for c in configure.call_args_list} == {
            f"standards:{linked_a.pk}",
            f"standards:{linked_b.pk}",
        }
        assert {r.project_id for r in running_executions()} == {linked_a.pk, linked_b.pk}
        assert not running_executions(unlinked).exists()
        assert all(r.triggered_by == "saved" for r in running_executions())
        assert summary["projects"] == 2
        assert summary["queued"] == 2

    def test_activation_records_its_own_trigger(self):
        project = baker.make("app.Project", tenant=self.tenant)
        project.standards.add(self.standard)

        with defer_patch():
            subscribers._on_standard_changed(self._activated())

        assert running_executions(project).get().triggered_by == "activated"

    def test_no_linked_projects_is_a_noop(self):
        with defer_patch() as configure:
            assert subscribers._on_standard_changed(self._saved()) is None
        configure.assert_not_called()

    def test_deleted_standard_is_a_noop(self):
        event = self._saved()
        self.standard.delete()

        with defer_patch() as configure:
            assert subscribers._on_standard_changed(event) is None
        configure.assert_not_called()
