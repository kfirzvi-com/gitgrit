from datetime import timedelta

import pytest
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from app.application.project_status_service import ProjectStatusService
from app.domain.models import StandardExecution

Status = StandardExecution.Status


def _stamp(execution, when):
    """Override auto_now_add created_at so order-sensitive tests are deterministic."""
    StandardExecution.objects.filter(pk=execution.pk).update(created_at=when)
    execution.refresh_from_db()
    return execution


class TestGetProjectStatus(APITestCase):
    def setUp(self):
        self.service = ProjectStatusService()
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant)

    def _standard(self, attach=True, critical=False, **kwargs):
        standard = baker.make("app.Standard", tenant=self.tenant, **kwargs)
        if attach:
            self.project.standards.add(standard)
        if critical:
            self.project.project_standards.filter(standard=standard).update(critical=True)
        return standard

    def _run(self, standard, status=Status.PASSED, score=100, **kwargs):
        """A manual default-branch run, so it counts."""
        kwargs.setdefault("event_type", "manual")
        kwargs.setdefault("ref", "")
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            score=score,
            status=status,
            **kwargs,
        )

    def status(self):
        return self.service.get_project_status(self.tenant, str(self.project.id))

    def test_empty_project_has_no_grade(self):
        result = self.status()
        assert result["grade"] is None
        assert result["reason"] == "no results yet"
        assert result["overall_score"] is None
        assert result["total_standards"] == 0
        assert result["top_offenders"] == []

    def test_letter_reason_and_overall_score_kept(self):
        for score in (95, 92, 98):
            self._run(self._standard(), score=score)
        failing = self._standard(name="lint")
        self._run(failing, Status.FAILED, score=40)

        result = self.status()

        assert result["grade"] == "B"  # 3 of 4 passed
        assert result["reason"] == "1 standard failing"
        assert result["overall_score"] == (95 + 92 + 98 + 40) / 4
        assert result["total_standards"] == 4
        assert result["passed"] == 3
        assert result["failed"] == 1

    def test_critical_failure_is_f_with_the_name(self):
        self._run(self._standard())
        self._run(self._standard(critical=True, name="No secrets"), Status.FAILED)

        result = self.status()

        assert result["grade"] == "F"
        assert result["reason"] == "No secrets failing"

    def test_ignores_running_skipped_and_other_branch_runs(self):
        standard = self._standard()
        self._run(standard, Status.PASSED)
        self._run(standard, Status.RUNNING, score=0)
        self._run(self._standard(), Status.SKIPPED)
        self._run(
            self._standard(), Status.FAILED, event_type="pull_request", ref="refs/heads/feature/x"
        )

        result = self.status()

        assert result["total_standards"] == 1
        assert result["grade"] == "A+"

    def test_top_offenders_critical_first_then_failed_then_errored(self):
        self._run(self._standard(name="passed"))
        self._run(self._standard(name="errored"), Status.ERROR, score=0)
        self._run(self._standard(name="low"), Status.FAILED, score=20)
        self._run(self._standard(name="high"), Status.FAILED, score=55)
        self._run(self._standard(name="gate", critical=True), Status.FAILED, score=90)

        result = self.status()

        offenders = result["top_offenders"]
        assert [o["name"] for o in offenders] == ["gate", "low", "high"]
        assert offenders[0]["critical"] is True
        assert offenders[1]["critical"] is False
        assert offenders[0]["status"] == "failed"

    def test_uses_only_latest_execution_per_standard(self):
        standard = self._standard()
        now = timezone.now()
        _stamp(self._run(standard, Status.FAILED, score=10), now - timedelta(hours=2))
        _stamp(self._run(standard, Status.PASSED, score=100), now)

        result = self.status()

        assert result["total_standards"] == 1
        assert result["overall_score"] == 100
        assert result["passed"] == 1
        assert result["failed"] == 0

    def test_detached_standard_executions_are_excluded(self):
        self._run(self._standard(), score=100)
        self._run(self._standard(attach=False), Status.FAILED, score=0)

        result = self.status()

        assert result["total_standards"] == 1
        assert result["overall_score"] == 100
        assert result["failed"] == 0

    def test_the_picture_before_a_run_leaves_that_run_out(self):
        standard = self._standard(name="lint")
        now = timezone.now()
        _stamp(self._run(standard, Status.PASSED), now - timedelta(hours=1))
        newest = _stamp(self._run(standard, Status.FAILED, score=0), now)

        before = self.service.get_project_status(
            self.tenant, str(self.project.id), exclude_execution_ids=[newest.pk]
        )

        assert (before["grade"], self.status()["grade"]) == ("A+", "D")

    def test_unknown_project_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.get_project_status(
                self.tenant, "00000000-0000-0000-0000-000000000000"
            )

    def test_malformed_uuid_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.get_project_status(self.tenant, "not-a-uuid")
