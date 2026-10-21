"""The /status/ snapshot reads the project's score: its newest scored commit
on the default branch, with the results behind it."""
import pytest
from model_bakery import baker
from rest_framework.test import APITestCase

from app.application.project_status_service import ProjectStatusService
from app.domain.models import StandardExecution
from tests.support import score_commit

Status = StandardExecution.Status


class TestGetProjectStatus(APITestCase):
    def setUp(self):
        self.service = ProjectStatusService()
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")

    def _commit(self, *results, sha="a" * 40, importance="major"):
        """Score one commit with ``(score, status)`` results, one standard each."""
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha=sha)
        for score, status in results:
            standard = baker.make("app.Standard", tenant=self.tenant)
            self.project.standards.add(standard)
            baker.make(
                "app.StandardExecution", project=self.project, standard=standard,
                standard_name=standard.name, score=score, status=status,
                commit_check=check, importance=importance,
            )
        return score_commit(self.project, sha)

    def _status(self):
        return self.service.get_project_status(self.tenant, str(self.project.id))

    def test_empty_project_has_no_grade(self):
        result = self._status()
        assert result["grade"] == "—"
        assert result["display"] == {"text": "—", "tone": "unknown", "spoken": "No score yet"}
        assert result["overall_score"] is None
        assert result["total_standards"] == 0
        assert result["top_offenders"] == []
        assert (result["score_failed"], result["commit_sha"]) == (False, None)

    def test_the_grade_is_the_score_as_the_app_shows_it(self):
        self._commit((95, Status.PASSED), (92, Status.PASSED), (98, Status.PASSED))

        result = self._status()

        assert result["grade"] == "A"
        assert result["display"]["tone"] == "healthy"
        assert result["overall_score"] == 95
        assert (result["total_standards"], result["passed"], result["failed"]) == (3, 3, 0)
        assert result["commit_sha"] == "a" * 40

    def test_a_failing_required_standard_makes_it_zero_with_the_reason(self):
        self._commit((90, Status.FAILED), importance="required")

        result = self._status()

        assert (result["overall_score"], result["score_failed"]) == (0, True)
        assert result["reason"].endswith("failing")

    def test_top_offenders_are_three_lowest_scoring(self):
        self._commit(*[(s, Status.FAILED) for s in (95, 30, 70, 20, 55)])

        offender_scores = [o["score"] for o in self._status()["top_offenders"]]

        assert offender_scores == [20, 30, 55]

    def test_excluding_a_run_gives_the_score_before_it(self):
        before = self._commit((100, Status.PASSED), sha="a" * 40)
        after = self._commit((0, Status.FAILED), sha="b" * 40)
        run = list(after.executions.values_list("pk", flat=True))

        result = self.service.get_project_status(
            self.tenant, str(self.project.id), exclude_execution_ids=run
        )

        assert result["commit_sha"] == before.commit_sha

    def test_unknown_project_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.get_project_status(
                self.tenant, "00000000-0000-0000-0000-000000000000"
            )

    def test_malformed_uuid_raises_value_error(self):
        with pytest.raises(ValueError):
            self.service.get_project_status(self.tenant, "not-a-uuid")
