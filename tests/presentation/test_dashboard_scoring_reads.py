"""Dashboard and badge reads: the dashboard counts projects by health, and
the badge scores only the standards attached to the project. (The attention
list's attachment rule is tested in tests/application/test_standard_results.py.)
"""
import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import scoring
from app.domain.models import StandardExecution
from app.application.workspace_health import WorkspaceHealth


def _execution(project, standard, score, status=StandardExecution.Status.PASSED):
    return baker.make(
        "app.StandardExecution",
        project=project,
        standard=standard,
        standard_name=standard.name,
        score=score,
        status=status,
    )


class TestWorkspaceHealth(TestCase):
    """The dashboard counts projects by health, from each one's commit
    score: failed only when a Required standard failed it."""

    def _project_scored(self, tenant, value, failed=False):
        project = baker.make("app.Project", tenant=tenant)
        check = baker.make("app.CommitCheck", project=project, branch=project.default_branch, commit_sha="a" * 40)
        baker.make(
            "app.CommitScore", project=project, commit_check=check, branch=project.default_branch,
            commit_sha="a" * 40, value=value, failed=failed, ordered_at=check.created_at,
        )
        return project

    def test_counts_projects_by_health(self):
        tenant = baker.make("app.Tenant")
        self._project_scored(tenant, None, failed=True)
        self._project_scored(tenant, 0)
        self._project_scored(tenant, 89)
        self._project_scored(tenant, 90)
        baker.make("app.Project", tenant=tenant)

        assert WorkspaceHealth.of(tenant) == WorkspaceHealth(failed=1, needs_attention=2, healthy=1, no_data=1)


@pytest.mark.django_db
class TestProjectBadge(TestCase):
    def test_badge_scores_only_attached_standards(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        attached = baker.make("app.Standard", tenant=tenant)
        detached = baker.make("app.Standard", tenant=tenant)
        project.standards.add(attached)
        check = baker.make(
            "app.CommitCheck", project=project, branch=project.default_branch, commit_sha="a" * 40,
            expected_standard_ids=[str(attached.pk)],
        )
        StandardExecution.objects.filter(
            pk__in=[
                _execution(project, attached, score=100).pk,
                _execution(project, detached, score=0, status=StandardExecution.Status.FAILED).pk,
            ]
        ).update(commit_check=check)
        scoring.score_check(check)

        svg = self.client.get(
            reverse("project_badge", args=[project.id])
        ).content.decode()

        assert "GitGrit compliance: A+" in svg

    def test_badge_shows_no_data_when_nothing_attached(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        detached = baker.make("app.Standard", tenant=tenant)
        _execution(project, detached, score=50)

        svg = self.client.get(
            reverse("project_badge", args=[project.id])
        ).content.decode()

        assert "GitGrit compliance: —" in svg
