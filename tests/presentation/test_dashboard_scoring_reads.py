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
from app.application.project_health_counts import ProjectHealthCounts


def _execution(project, standard, score, status=StandardExecution.Status.PASSED):
    return baker.make(
        "app.StandardExecution",
        project=project,
        standard=standard,
        standard_name=standard.name,
        score=score,
        status=status,
    )


class TestProjectHealthCounts(TestCase):
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

        counts = ProjectHealthCounts.for_workspace(tenant)
        assert counts.as_dict() == {"failed": 1, "needs_attention": 2, "healthy": 1, "no_data": 1}
        # Each project that needs attention, as itself: failed first, then lowest.
        assert [s.failed for _, s in counts.attention] == [True, False, False]
        assert [s.value for _, s in counts.attention][1:] == [0, 89]

    def test_a_stack_node_counts_its_projects_and_has_no_grade_of_its_own(self):
        from app.presentation.architecture import workspace_graph

        tenant = baker.make("app.Tenant")
        stack = baker.make("app.Stack", tenant=tenant)
        for project in (self._project_scored(tenant, None, failed=True), self._project_scored(tenant, 95)):
            project.root_component.stacks.add(stack)

        [node] = workspace_graph(tenant)["stacks"]

        assert node["project_health"] == {"failed": 1, "needs_attention": 0, "healthy": 1, "no_data": 0}
        assert not {"health", "score", "score_text", "score_shade"} & set(node)


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

    def test_the_dashboard_counts_list_their_projects_with_links(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        failed = TestProjectHealthCounts._project_scored(self, tenant, None, failed=True)
        baker.make("app.Stack", tenant=tenant)

        body = self.client.get(reverse("dashboard")).content.decode()

        listed = body.split('data-count-projects="failed"')[1].split("</ul>")[0]
        assert f'href="{reverse("project_detail", args=[failed.pk])}"' in listed
        assert failed.name in listed and ">F</span>" in listed
