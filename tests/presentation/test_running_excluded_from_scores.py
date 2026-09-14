"""An in-flight run must not move any score.

Manual runs now create their ``StandardExecution`` row RUNNING (score 0) and
let the background worker fill it in. Every "latest result per standard" read
therefore has to skip RUNNING rows, or starting a run would look like an
instant regression to 0% on the project page, the badge and the dashboard.
The project page's "Recent Activity" list still shows the RUNNING row.
"""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import StandardExecution
from app.presentation.architecture import attention_items, latest_scores_by_project

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _login_member(client):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


def _passed_then_running(project, standard):
    """A finished 100% result, then a newer in-flight run of the same standard."""
    baker.make(
        "app.StandardExecution",
        project=project,
        standard=standard,
        standard_name=standard.name,
        score=100,
        status=StandardExecution.Status.PASSED,
    )
    return baker.make(
        "app.StandardExecution",
        project=project,
        standard=standard,
        standard_name=standard.name,
        score=0,
        status=StandardExecution.Status.RUNNING,
    )


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestRunningRowsDoNotMoveScores(TestCase):
    def setUp(self):
        _, self.tenant = _login_member(self.client)
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.standard = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(self.standard)
        self.running = _passed_then_running(self.project, self.standard)

    def test_project_page_score_ignores_the_running_row(self):
        resp = self.client.get(reverse("project_detail", args=[self.project.pk]))

        assert resp.status_code == 200
        assert resp.context["compliance_score"] == 100
        assert [ex.pk for ex in resp.context["latest_executions"]] != [
            self.running.pk
        ]
        # ... but it is still visible in the activity list.
        assert self.running.pk in [
            ex.pk for ex in resp.context["recent_executions"]
        ]

    def test_badge_score_ignores_the_running_row(self):
        svg = self.client.get(
            reverse("project_badge", args=[self.project.pk])
        ).content.decode()

        assert "100%" in svg

    def test_latest_scores_by_project_ignores_the_running_row(self):
        latest = latest_scores_by_project(self.tenant)

        assert latest[self.project.id][self.standard.id]["score"] == 100

    def test_attention_list_ignores_the_running_row(self):
        # A RUNNING row scores 0; without the exclusion it would show as
        # critical and hide the real (passing) latest result for the pair.
        assert attention_items(self.tenant) == []

    def test_execution_detail_page_shows_the_run_as_running_and_refreshes(self):
        resp = self.client.get(
            reverse("standard_execution_detail", args=[self.running.pk])
        )

        assert resp.status_code == 200
        html = resp.content.decode()
        assert "badge-info" in html
        assert "Running in the background" in html
        assert 'http-equiv="refresh"' in html
        assert "Score:" not in html
