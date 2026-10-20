"""Dashboard, stack and badge reads show grade letters, one rule per test.

Attachment defines which standards apply to a project; detaching (or deleting)
a standard removes its history from the project's grade. (The attention list's
version of this rule is tested in tests/application/test_standard_results.py.)
The workspace and a stack are as good as their worst graded project.
"""
import re

import pytest
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from model_bakery import baker

from app.application.grading_service import grades_for_tenant
from app.domain.models import Component, StandardExecution
from app.presentation.architecture import workspace_graph

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _execution(project, standard, status=StandardExecution.Status.PASSED, score=100):
    """A manual run that read the default branch, so it counts."""
    return baker.make(
        "app.StandardExecution",
        project=project,
        standard=standard,
        standard_name=standard.name,
        event_type="manual",
        ref="",
        score=score,
        status=status,
    )


def _attach(project, *standards, critical=False):
    for standard in standards:
        project.standards.add(standard)
    if critical:
        project.project_standards.filter(standard__in=standards).update(level="critical")


def _login_member(client, tenant):
    user = baker.make("app.User")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user


def _stack_with(tenant, *projects, name="Stack"):
    stack = baker.make("app.Stack", tenant=tenant, name=name)
    for project in projects:
        component, _ = Component.objects.get_or_create(
            tenant=tenant, project=project, path="", defaults={"name": project.name}
        )
        baker.make("app.ComponentStack", component=component, stack=stack)
    return stack


@pytest.mark.django_db
class TestProjectBadge(TestCase):
    def test_badge_shows_the_letter_not_a_percentage(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        attached = baker.make("app.Standard", tenant=tenant)
        detached = baker.make("app.Standard", tenant=tenant)
        _attach(project, attached)
        _execution(project, attached)
        _execution(project, detached, StandardExecution.Status.FAILED, score=0)

        svg = self.client.get(
            reverse("project_badge", args=[project.id])
        ).content.decode()

        assert ">A+<" in svg
        assert re.search(r">\d+%<", svg) is None  # no percentage text
        assert "#00c584" in svg  # good tone (--gg-grade-good)

    def test_badge_f_is_red(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        gate = baker.make("app.Standard", tenant=tenant)
        _attach(project, gate, critical=True)
        _execution(project, gate, StandardExecution.Status.FAILED)

        svg = self.client.get(
            reverse("project_badge", args=[project.id])
        ).content.decode()

        assert ">F<" in svg
        assert "#f14e46" in svg  # failing tone (--gg-grade-failing)

    def test_badge_shows_no_grade_when_nothing_attached(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        detached = baker.make("app.Standard", tenant=tenant)
        _execution(project, detached)

        svg = self.client.get(
            reverse("project_badge", args=[project.id])
        ).content.decode()

        assert "no grade" in svg


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestWorkspaceGrade(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        _login_member(self.client, self.tenant)

    def _project(self, name, letter_status, critical=False):
        """A project whose single attached standard has the given status."""
        project = baker.make("app.Project", tenant=self.tenant, name=name)
        standard = baker.make("app.Standard", tenant=self.tenant, name=f"{name}-std")
        _attach(project, standard, critical=critical)
        if letter_status is not None:
            _execution(project, standard, letter_status)
        return project

    def test_workspace_is_the_worst_graded_project_and_ungraded_are_ignored(self):
        good = self._project("good", StandardExecution.Status.PASSED)
        failing = self._project("failing", StandardExecution.Status.FAILED, critical=True)
        ungraded = self._project("ungraded", None)
        _stack_with(self.tenant, good, failing, ungraded)

        resp = self.client.get(reverse("dashboard"))

        assert resp.status_code == 200
        assert resp.context["workspace_grade"] == "F"
        assert resp.context["workspace_tone"] == "failing"
        assert 'data-workspace-grade="F"' in resp.content.decode()
        assert "% compliance" not in resp.content.decode()

    def test_workspace_with_only_ungraded_projects_shows_no_letter(self):
        ungraded = self._project("ungraded", None)
        _stack_with(self.tenant, ungraded)

        resp = self.client.get(reverse("dashboard"))

        assert resp.context["workspace_grade"] is None
        assert "data-workspace-grade" not in resp.content.decode()

    def test_stack_page_and_list_show_the_worst_project_grade(self):
        good = self._project("good", StandardExecution.Status.PASSED)
        failed = self._project("failed", StandardExecution.Status.FAILED)
        ungraded = self._project("ungraded", None)
        stack = _stack_with(self.tenant, good, failed, ungraded, name="Mixed")
        clean = _stack_with(self.tenant, good, name="Clean")

        page = self.client.get(reverse("stack_detail", args=[stack.pk]))
        listing = self.client.get(reverse("stack_list"))

        assert page.context["stack_grade"] == "D"
        assert page.context["stack_grade_tone"] == "failing"
        assert 'data-stack-grade="D"' in page.content.decode()
        by_name = {s.name: s for s in listing.context["stacks"]}
        assert by_name["Mixed"].grade == "D"
        assert by_name["Clean"].grade == "A+"
        assert listing.content.decode().count("data-stack-grade=") == 2

    def test_map_nodes_carry_grade_and_health_not_score(self):
        failed = self._project("failed", StandardExecution.Status.FAILED)
        _stack_with(self.tenant, failed, name="S")

        graph = workspace_graph(self.tenant, grades_for_tenant(self.tenant))

        node = graph["stacks"][0]
        assert node["grade"] == "D"
        assert node["health"] == "failing"
        assert node["issues"] == ["failed — D (1 standard failing)"]
        assert "score" not in node


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestProjectListBoxes(TestCase):
    """Each project's box on the Projects list shows its letter, no last run."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        _login_member(self.client, self.tenant)

    def _project(self, name, status=None, critical=False, event_type="manual"):
        project = baker.make("app.Project", tenant=self.tenant, name=name)
        standard = baker.make("app.Standard", tenant=self.tenant, name=f"{name}-std")
        _attach(project, standard, critical=critical)
        if status is not None:
            ex = _execution(project, standard, status)
            StandardExecution.objects.filter(pk=ex.pk).update(event_type=event_type)
        return project

    def test_box_shows_letter_and_no_results_otherwise_and_no_last_run(self):
        self._project("good", StandardExecution.Status.PASSED, event_type="pull_request")
        self._project("failing", StandardExecution.Status.FAILED, critical=True)
        self._project("fresh")

        resp = self.client.get(reverse("project_list"))
        html = resp.content.decode()

        assert 'data-grade="A+"' in html
        assert 'data-grade="F"' in html
        assert "data-failing" in html  # F is not colour alone
        assert html.count("No results yet") == 1
        assert "data-last-run" not in html
        assert "Last run" not in html

    def test_card_and_letter_wear_the_grade_tone(self):
        self._project("good", StandardExecution.Status.PASSED, event_type="pull_request")
        self._project("failing", StandardExecution.Status.FAILED, critical=True)
        self._project("weak", StandardExecution.Status.FAILED)  # D
        fair = self._project("fair", StandardExecution.Status.FAILED)  # 3 of 4 pass: B
        for i in range(3):
            extra = baker.make("app.Standard", tenant=self.tenant, name=f"fair-ok{i}")
            _attach(fair, extra)
            _execution(fair, extra)
        self._project("fresh")

        html = self.client.get(reverse("project_list")).content.decode()

        assert 'gg-tone-good" data-grade="A+"' in html
        assert 'gg-tone-attention" data-grade="B"' in html
        assert 'gg-tone-failing" data-grade="D"' in html
        assert 'gg-tone-failing" data-grade="F"' in html
        assert "gg-tone-card gg-tone-unknown" in html and "data-no-grade" in html

    def test_list_query_count_does_not_grow_with_projects(self):
        self._project("one", StandardExecution.Status.PASSED)
        self.client.get(reverse("project_list"))  # warm caches
        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse("project_list"))
        for i in range(4):
            self._project(f"more-{i}", StandardExecution.Status.PASSED)
        with CaptureQueriesContext(connection) as many:
            self.client.get(reverse("project_list"))
        assert len(many) == len(few)
