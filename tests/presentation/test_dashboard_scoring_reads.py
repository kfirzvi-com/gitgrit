"""Dashboard and badge scoring reads count only currently-attached standards.

Attachment defines which standards apply to a project; detaching (or deleting)
a standard must also remove its execution history from the project's score and
from the attention list, so old runs stop dragging the numbers.
"""
import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import StandardExecution
from app.presentation.architecture import attention_items, latest_scores_by_project


def _execution(project, standard, score, status=StandardExecution.Status.PASSED):
    return baker.make(
        "app.StandardExecution",
        project=project,
        standard=standard,
        standard_name=standard.name,
        score=score,
        status=status,
    )


@pytest.mark.django_db
class TestLatestScoresByProject(TestCase):
    def test_only_attached_standards_count(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        attached = baker.make("app.Standard", tenant=tenant)
        detached = baker.make("app.Standard", tenant=tenant)
        project.standards.add(attached)
        _execution(project, attached, score=90)
        _execution(project, detached, score=10)

        latest = latest_scores_by_project(tenant)

        assert set(latest[project.id]) == {attached.id}
        assert latest[project.id][attached.id]["score"] == 90

    def test_deleted_standard_executions_are_excluded(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        standard = baker.make("app.Standard", tenant=tenant)
        project.standards.add(standard)
        _execution(project, standard, score=10)
        standard.delete()

        assert latest_scores_by_project(tenant) == {}

    def test_attachment_is_per_project(self):
        tenant = baker.make("app.Tenant")
        with_standard = baker.make("app.Project", tenant=tenant)
        without_standard = baker.make("app.Project", tenant=tenant)
        standard = baker.make("app.Standard", tenant=tenant)
        with_standard.standards.add(standard)
        _execution(with_standard, standard, score=80)
        _execution(without_standard, standard, score=80)

        latest = latest_scores_by_project(tenant)

        assert with_standard.id in latest
        assert without_standard.id not in latest


@pytest.mark.django_db
class TestAttentionItems(TestCase):
    def test_detached_standard_failure_is_not_raised(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        attached = baker.make("app.Standard", tenant=tenant)
        detached = baker.make("app.Standard", tenant=tenant)
        project.standards.add(attached)
        _execution(
            project, attached, score=20, status=StandardExecution.Status.FAILED
        )
        _execution(
            project, detached, score=5, status=StandardExecution.Status.FAILED
        )

        items = attention_items(tenant)

        assert [i["standard_name"] for i in items] == [attached.name]


@pytest.mark.django_db
class TestProjectBadge(TestCase):
    def test_badge_scores_only_attached_standards(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        attached = baker.make("app.Standard", tenant=tenant)
        detached = baker.make("app.Standard", tenant=tenant)
        project.standards.add(attached)
        _execution(project, attached, score=100)
        _execution(
            project, detached, score=0, status=StandardExecution.Status.FAILED
        )

        svg = self.client.get(
            reverse("project_badge", args=[project.id])
        ).content.decode()

        assert "100%" in svg

    def test_badge_shows_no_data_when_nothing_attached(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        detached = baker.make("app.Standard", tenant=tenant)
        _execution(project, detached, score=50)

        svg = self.client.get(
            reverse("project_badge", args=[project.id])
        ).content.decode()

        assert "no data" in svg
