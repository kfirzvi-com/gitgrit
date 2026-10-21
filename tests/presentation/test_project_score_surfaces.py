"""The badge and the stack diagram's components show the project score: a
failing Required standard makes them 0 and says why."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import StandardExecution
from app.presentation.architecture import latest_scores_by_project, stack_graph
from tests.support import score_commit

Status = StandardExecution.Status


class ProjectScoreSurfacesTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self.standard = baker.make("app.Standard", tenant=self.tenant, name="No secrets")
        self.project.standards.add(self.standard)
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha="a" * 40)
        baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard,
            standard_name="No secrets", status=Status.FAILED, score=90, commit_check=check,
            importance="required", ref="main",
        )
        score_commit(self.project, "a" * 40)

    def test_the_badge_shows_zero_in_red(self):
        svg = self.client.get(reverse("project_badge", args=[self.project.pk])).content.decode()

        assert "GitGrit compliance: 0%" in svg
        assert "#f44336" in svg

    def test_a_component_shows_the_project_score_and_why(self):
        stack = baker.make("app.Stack", tenant=self.tenant)
        component = self.project.root_component
        component.stacks.add(stack)

        graph = stack_graph(stack, latest_scores_by_project(self.tenant))
        node = next(n for n in graph["components"] if n["id"] == str(component.id))

        assert (node["score"], node["health"], node["issues"]) == (0, "critical", ["No secrets failing"])
