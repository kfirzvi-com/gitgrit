from datetime import timedelta

import pytest
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from app.application.project_status_service import ProjectStatusService
from app.domain.models import StandardExecution


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

    def test_empty_project_returns_unknown_grade(self):
        result = self.service.get_project_status(self.tenant, str(self.project.id))
        assert result["grade"] == "unknown"
        assert result["overall_score"] is None
        assert result["total_standards"] == 0
        assert result["top_offenders"] == []

    def test_grade_excellent_when_all_scores_high(self):
        for score in (95, 92, 98):
            standard = baker.make("app.Standard", tenant=self.tenant)
            self.project.standards.add(standard)
            baker.make(
                "app.StandardExecution",
                project=self.project,
                standard=standard,
                score=score,
                status=StandardExecution.Status.PASSED,
            )
        result = self.service.get_project_status(self.tenant, str(self.project.id))
        assert result["grade"] == "excellent"
        assert result["overall_score"] == (95 + 92 + 98) / 3
        assert result["total_standards"] == 3
        assert result["passed"] == 3
        assert result["failed"] == 0

    def test_ignores_running_skipped_and_errored(self):
        standard = baker.make("app.Standard", tenant=self.tenant)
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            score=80,
            status=StandardExecution.Status.RUNNING,
        )
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=baker.make("app.Standard", tenant=self.tenant),
            score=80,
            status=StandardExecution.Status.SKIPPED,
        )
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=baker.make("app.Standard", tenant=self.tenant),
            score=80,
            status=StandardExecution.Status.ERROR,
        )
        result = self.service.get_project_status(self.tenant, str(self.project.id))
        assert result["total_standards"] == 0
        assert result["grade"] == "unknown"

    def test_top_offenders_are_three_lowest_scoring(self):
        scores = [95, 30, 70, 20, 55]
        for score in scores:
            standard = baker.make("app.Standard", tenant=self.tenant)
            self.project.standards.add(standard)
            baker.make(
                "app.StandardExecution",
                project=self.project,
                standard=standard,
                score=score,
                status=StandardExecution.Status.FAILED,
            )
        result = self.service.get_project_status(self.tenant, str(self.project.id))
        offender_scores = [o["score"] for o in result["top_offenders"]]
        assert offender_scores == [20, 30, 55]

    def test_uses_only_latest_execution_per_standard(self):
        standard = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(standard)
        now = timezone.now()
        old = baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            score=10,
            status=StandardExecution.Status.FAILED,
        )
        _stamp(old, now - timedelta(hours=2))
        newer = baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            score=100,
            status=StandardExecution.Status.PASSED,
        )
        _stamp(newer, now)

        result = self.service.get_project_status(self.tenant, str(self.project.id))
        # Only the newer run counts: one standard, perfect score.
        assert result["total_standards"] == 1
        assert result["overall_score"] == 100
        assert result["passed"] == 1
        assert result["failed"] == 0

    def test_detached_standard_executions_are_excluded_from_score(self):
        attached = baker.make("app.Standard", tenant=self.tenant)
        detached = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(attached)
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=attached,
            score=100,
            status=StandardExecution.Status.PASSED,
        )
        baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=detached,
            score=0,
            status=StandardExecution.Status.FAILED,
        )

        result = self.service.get_project_status(self.tenant, str(self.project.id))

        assert result["total_standards"] == 1
        assert result["overall_score"] == 100
        assert result["failed"] == 0

    def test_unknown_project_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.get_project_status(
                self.tenant, "00000000-0000-0000-0000-000000000000"
            )

    def test_malformed_uuid_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.get_project_status(self.tenant, "not-a-uuid")
