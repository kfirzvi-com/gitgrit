from datetime import timedelta

import pytest
from django.utils import timezone
from model_bakery import baker
from rest_framework.test import APITestCase

from app.application.project_status_service import ProjectStatusService
from app.domain.models import PolicyExecution


def _stamp(execution, when):
    """Override auto_now_add created_at so order-sensitive tests are deterministic."""
    PolicyExecution.objects.filter(pk=execution.pk).update(created_at=when)
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
        assert result["total_policies"] == 0
        assert result["top_offenders"] == []

    def test_grade_excellent_when_all_scores_high(self):
        for score in (95, 92, 98):
            policy = baker.make("app.Policy", tenant=self.tenant)
            baker.make(
                "app.PolicyExecution",
                project=self.project,
                policy=policy,
                score=score,
                status=PolicyExecution.Status.PASSED,
            )
        result = self.service.get_project_status(self.tenant, str(self.project.id))
        assert result["grade"] == "excellent"
        assert result["overall_score"] == (95 + 92 + 98) / 3
        assert result["total_policies"] == 3
        assert result["passed"] == 3
        assert result["failed"] == 0

    def test_ignores_running_skipped_and_errored(self):
        policy = baker.make("app.Policy", tenant=self.tenant)
        baker.make(
            "app.PolicyExecution",
            project=self.project,
            policy=policy,
            score=80,
            status=PolicyExecution.Status.RUNNING,
        )
        baker.make(
            "app.PolicyExecution",
            project=self.project,
            policy=baker.make("app.Policy", tenant=self.tenant),
            score=80,
            status=PolicyExecution.Status.SKIPPED,
        )
        baker.make(
            "app.PolicyExecution",
            project=self.project,
            policy=baker.make("app.Policy", tenant=self.tenant),
            score=80,
            status=PolicyExecution.Status.ERROR,
        )
        result = self.service.get_project_status(self.tenant, str(self.project.id))
        assert result["total_policies"] == 0
        assert result["grade"] == "unknown"

    def test_top_offenders_are_three_lowest_scoring(self):
        scores = [95, 30, 70, 20, 55]
        for score in scores:
            policy = baker.make("app.Policy", tenant=self.tenant)
            baker.make(
                "app.PolicyExecution",
                project=self.project,
                policy=policy,
                score=score,
                status=PolicyExecution.Status.FAILED,
            )
        result = self.service.get_project_status(self.tenant, str(self.project.id))
        offender_scores = [o["score"] for o in result["top_offenders"]]
        assert offender_scores == [20, 30, 55]

    def test_uses_only_latest_execution_per_policy(self):
        policy = baker.make("app.Policy", tenant=self.tenant)
        now = timezone.now()
        old = baker.make(
            "app.PolicyExecution",
            project=self.project,
            policy=policy,
            score=10,
            status=PolicyExecution.Status.FAILED,
        )
        _stamp(old, now - timedelta(hours=2))
        newer = baker.make(
            "app.PolicyExecution",
            project=self.project,
            policy=policy,
            score=100,
            status=PolicyExecution.Status.PASSED,
        )
        _stamp(newer, now)

        result = self.service.get_project_status(self.tenant, str(self.project.id))
        # Only the newer run counts: one policy, perfect score.
        assert result["total_policies"] == 1
        assert result["overall_score"] == 100
        assert result["passed"] == 1
        assert result["failed"] == 0

    def test_unknown_project_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.get_project_status(
                self.tenant, "00000000-0000-0000-0000-000000000000"
            )

    def test_malformed_uuid_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.get_project_status(self.tenant, "not-a-uuid")
