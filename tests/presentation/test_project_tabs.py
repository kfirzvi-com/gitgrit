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
from tests.support import score_commit

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
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha="a" * 40)
        return baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=standard.name, status=status, score=score, ref="main", commit_check=check,
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
        score_commit(self.project, "a" * 40)

        response = self._page()

        # The error is left out of the average: (100 + 0) / 2.
        self.assertEqual(response.context["compliance_score"], 50)
        self.assertEqual(
            response.context["health_breakdown"],
            {"required_failed": 0, "passed": 1, "failed": 1, "errored": 1, "failures": 1, "total": 3},
        )
        body = response.content.decode()
        self.assertIn('data-score-value>D<', body)
        self.assertIn("No Required failures", body)
        self.assertIn("Based on 3 standards", body)
        self.assertNotIn(">50%", body)
        self.assertIn("See results by commit", body)
        self.assertIn('data-grade-scale', body)
        self.assertIn("data-health-breakdown", body)

    def test_results_and_standards_load_when_first_opened(self):
        body = self._page().content.decode()
        self.assertIn(f'hx-get="{reverse("project_history", args=[self.project.pk])}"', body)
        self.assertIn(f'hx-get="{reverse("project_standards", args=[self.project.pk])}?embed=tab"', body)
        self.assertEqual(body.count('hx-trigger="tab-open once"'), 2)

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


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class OverviewRequiredFailuresTests(TestCase):
    """The Overview counts Required failures apart from the others and
    leaves which standard failed to the Results tab."""

    def setUp(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=tenant, default_branch="main")
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha="a" * 40)
        for name, status, importance in (
            ("No secrets", Status.FAILED, "required"),
            ("License", Status.ERROR, "required"),
            ("README", Status.FAILED, "major"),
            ("Linter", Status.PASSED, "minor"),
        ):
            standard = baker.make("app.Standard", tenant=tenant, name=name)
            self.project.standards.add(standard)
            baker.make(
                "app.StandardExecution", project=self.project, standard=standard, standard_name=name,
                status=status, score=50, commit_check=check, importance=importance,
            )
        score_commit(self.project, "a" * 40)

    def test_required_failures_are_counted_apart_and_not_named(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]))

        self.assertEqual(
            response.context["health_breakdown"],
            {"required_failed": 2, "passed": 1, "failed": 1, "errored": 0, "failures": 3, "total": 4},
        )
        body = response.content.decode()
        self.assertIn('data-required-failed="2"', body)
        self.assertIn("2 Required standards failed", body)
        self.assertIn('data-score-value>F<', body)
        self.assertIn("gg-tone-card-failed", body)
        self.assertIn('gg-chip gg-chip-current gg-tone-bg-failed" aria-current="true">F<', body)
        self.assertNotIn("data-score-reason", body)

    def test_the_overview_and_results_tabs_show_the_same_bar_and_legend(self):
        overview = self.client.get(reverse("project_detail", args=[self.project.pk])).content.decode()
        results = self.client.get(reverse("project_history", args=[self.project.pk]), HTTP_HX_REQUEST="true").content.decode()

        for body in (overview, results):
            with self.subTest(tab="overview" if body is overview else "results"):
                self.assertIn('data-segment="required_failed"', body)
                self.assertIn('data-segment="failed"', body)
                self.assertRegex(body, r'data-legend="required_failed">\s*<span class="gg-importance-icon')
                self.assertIn("<b>2</b> Required failed", body)
                self.assertIn('<b>1</b> <span class="opacity-70">other failed', body)
                self.assertIn('<b>0</b> <span class="opacity-70">could not run', body)

    def test_the_results_tab_shows_each_standard_as_a_number_and_the_commit_as_a_letter(self):
        body = self.client.get(reverse("project_history", args=[self.project.pk]), HTTP_HX_REQUEST="true").content.decode()

        self.assertRegex(body, r'data-commit-score><span class="gg-score[^"]*"[^>]*>F</span>')
        self.assertIn('aria-label="Score 50 out of 100"', body)
        self.assertNotIn('aria-label="Grade D', body)
