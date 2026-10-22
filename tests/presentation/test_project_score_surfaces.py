"""The badge and the stack diagram's components show the project score: a
failing Required standard makes them 0 and says why."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import StandardExecution
from app.presentation.score_tones import ScoreToneStyle
from app.presentation.architecture import stack_graph
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

    def test_a_failed_project_reads_f_in_deep_red(self):
        svg = self.client.get(reverse("project_badge", args=[self.project.pk])).content.decode()

        assert "GitGrit compliance: F" in svg
        assert ScoreToneStyle.for_tone("failed").color in svg

    def test_a_component_shows_the_project_score_and_why(self):
        stack = baker.make("app.Stack", tenant=self.tenant)
        component = self.project.root_component
        component.stacks.add(stack)

        graph = stack_graph(stack)
        node = next(n for n in graph["components"] if n["id"] == str(component.id))

        assert (node["score"], node["score_text"], node["health"], node["issues"]) == (
            None, "F", "failed", ["No secrets failing"]
        )

    def test_a_project_card_glows_in_its_letter_and_says_when_the_project_failed(self):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

        body = self.client.get(reverse("project_list")).content.decode()

        assert 'gg-tone-card gg-tone-card-failed" data-project-card="failed"' in body
        assert ">F</span>" in body
        assert "Project failed!" in body

    def test_a_stack_card_reads_as_its_least_healthy_project(self):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        stack = baker.make("app.Stack", tenant=self.tenant, name="Orders")
        self.project.root_component.stacks.add(stack)

        body = self.client.get(reverse("stack_list")).content.decode()

        assert 'gg-tone-card gg-tone-card-failed" data-stack-card="failed"' in body
        assert "1 project<br>failed" in body
