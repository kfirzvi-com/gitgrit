"""The project page's three tabs: Overview (health score, its pass / fail /
error breakdown, and About), Results (by commit, loaded when opened) and
Standards (the embedded picker, loaded when opened).

``#compliance``, where ``standards.failing`` notifications link, is the
Results tab's panel, so those links open it.
"""
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import StandardExecution

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

Status = StandardExecution.Status


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class ProjectTabsTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")

    def _page(self):
        return self.client.get(reverse("project_detail", args=[self.project.pk]))

    def _result(self, status, score):
        standard = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)
        self.project.standards.add(standard)
        return baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=standard.name, status=status, score=score, ref="main",
        )

    def test_renders_the_three_tabs_overview_first(self):
        body = self._page().content.decode()
        overview = body.index('aria-label="Overview"')
        results = body.index('aria-label="Results"')
        standards = body.index('aria-label="Standards"')
        self.assertLess(overview, results)
        self.assertLess(results, standards)
        self.assertIn('data-tab="overview" checked', body)

    def test_notification_links_land_on_the_results_tab(self):
        body = self._page().content.decode()
        self.assertLess(body.index('aria-label="Results"'), body.index('id="compliance"'))
        self.assertLess(body.index('id="compliance"'), body.index('id="project-history"'))
        self.assertIn("compliance: \"results\"", body)

    def test_overview_shows_the_score_without_a_percent_and_its_breakdown(self):
        self._result(Status.PASSED, 100)
        self._result(Status.FAILED, 0)
        self._result(Status.ERROR, 0)

        response = self._page()

        self.assertEqual(response.context["compliance_score"], 33)
        self.assertEqual(response.context["health_breakdown"], {"passed": 1, "failed": 1, "errored": 1})
        body = response.content.decode()
        self.assertIn("--value:33", body)
        self.assertNotIn("33%", body)
        self.assertIn("data-health-breakdown", body)

    def test_results_and_standards_load_when_first_opened(self):
        body = self._page().content.decode()
        self.assertIn(f'hx-get="{reverse("project_history", args=[self.project.pk])}"', body)
        self.assertIn(f'hx-get="{reverse("project_standards", args=[self.project.pk])}?embed=tab"', body)

    def test_saving_standards_returns_to_the_standards_tab(self):
        standard = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)

        response = self.client.post(
            reverse("project_standards", args=[self.project.pk]), {"standards": [standard.pk]}
        )

        self.assertRedirects(
            response, reverse("project_detail", args=[self.project.pk]) + "#standards",
            fetch_redirect_response=False,
        )
        self.assertEqual(list(self.project.standards.all()), [standard])

    def test_the_embedded_picker_saves_to_the_project(self):
        response = self.client.get(reverse("project_standards", args=[self.project.pk]) + "?embed=tab", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(f'action="{reverse("project_standards", args=[self.project.pk])}"', body)
        self.assertNotIn("<html", body)
