"""The Results tab's order: failed standards (critical first, errored with
them), then passed, then the rest, under "Failed standards" / "Passed
standards" / "Other" headings; and the Overview card's link to the tab."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import commit_checks
from app.application.standard_results import group_results
from app.domain.models import StandardExecution

Status = StandardExecution.Status


def _ex(name, status, critical=False):
    return SimpleNamespace(standard_name=name, status=status, level="critical" if critical else "high")


class GroupResultsTests(SimpleTestCase):
    def test_failed_then_passed_then_other_with_critical_first(self):
        results = [
            _ex("Pass B", Status.PASSED),
            _ex("Running", Status.RUNNING),
            _ex("Fail B", Status.FAILED),
            _ex("Crit", Status.FAILED, critical=True),
            _ex("Pass A", Status.PASSED),
            _ex("Broken", Status.ERROR),
            _ex("Fail A", Status.FAILED),
        ]

        groups = group_results(results)

        self.assertEqual(
            [(key, heading) for key, heading, _ in groups],
            [("failed", "Failed standards"), ("passed", "Passed standards"), ("other", "Other")],
        )
        names = {key: [r.standard_name for r in rows] for key, _, rows in groups}
        self.assertEqual(names["failed"], ["Crit", "Fail A", "Fail B", "Broken"])
        self.assertEqual(names["passed"], ["Pass A", "Pass B"])
        self.assertEqual(names["other"], ["Running"])

    def test_empty_groups_are_left_out(self):
        groups = group_results([_ex("Only", Status.PASSED)])

        self.assertEqual([key for key, _, _ in groups], ["passed"])
        self.assertEqual(group_results([]), [])


class ResultsTabOrderTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        self.tenant = tenant
        self.project = baker.make("app.Project", tenant=tenant, default_branch="main")
        platform = mock.Mock()
        platform.list_branches.return_value = ["main"]
        platform.list_commits.return_value = [
            {"sha": "a" * 40, "message": "c", "author": "D", "date": "2026-10-01T10:00:00Z", "url": ""},
        ]
        patch = mock.patch.object(commit_checks, "_client", return_value=platform)
        patch.start()
        self.addCleanup(patch.stop)
        self.check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha="a" * 40)

    def _result(self, name, status, critical=False):
        standard = baker.make("app.Standard", tenant=self.tenant, name=name)
        self.project.standards.add(standard)
        return baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=name, status=status, level="critical" if critical else "high", score=0, commit_check=self.check,
        )

    def _body(self):
        return self.client.get(reverse("project_history", args=[self.project.pk])).content.decode()

    def test_failed_sit_above_passed_under_their_headings(self):
        self._result("Alpha passes", Status.PASSED)
        self._result("Beta fails", Status.FAILED)
        self._result("Gamma critical", Status.FAILED, critical=True)

        body = self._body()

        order = [body.index(text) for text in (
            "Failed standards", "Gamma critical", "Beta fails", "Passed standards", "Alpha passes",
        )]
        self.assertEqual(order, sorted(order))
        self.assertNotIn(">Other<", body)

    def test_a_heading_is_skipped_when_its_group_is_empty(self):
        self._result("Alpha passes", Status.PASSED)

        body = self._body()

        self.assertIn("Passed standards", body)
        self.assertNotIn("Failed standards", body)


class OverviewResultsLinkTests(TestCase):
    def test_the_results_link_sits_above_the_last_run_line_once(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        project = baker.make("app.Project", tenant=tenant, default_branch="main")
        standard = baker.make("app.Standard", tenant=tenant, enabled=True, draft=False)
        project.standards.add(standard)
        baker.make(
            "app.StandardExecution", project=project, standard=standard, standard_name=standard.name,
            status=Status.PASSED, score=100, ref="main", event_type="manual",
        )

        body = self.client.get(reverse("project_detail", args=[project.pk])).content.decode()

        self.assertEqual(body.count("data-results-link"), 1)
        self.assertIn('<strong class="font-semibold underline">results</strong>', body)
        self.assertLess(body.index("data-results-link"), body.index("Last run:"))
