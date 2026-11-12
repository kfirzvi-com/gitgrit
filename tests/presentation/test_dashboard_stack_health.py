"""The dashboard shows the workspace's project health and each stack's,
worst first."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from tests.support import score_commit


class DashboardStackHealthTests(TestCase):
    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="owner")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def _stack(self, name, *projects):
        stack = baker.make("app.Stack", tenant=self.tenant, name=name)
        for project in projects:
            stack.components.add(
                project.components.first()
                or baker.make("app.Component", tenant=self.tenant, project=project)
            )
        return stack

    def test_stacks_are_listed_worst_first_with_their_own_counts(self):
        # A project with no grade needs attention, so "Zed" comes before "Alpha".
        ungraded = baker.make("app.Project", tenant=self.tenant)
        alpha = self._stack("Alpha")
        zed = self._stack("Zed", ungraded)

        response = self.client.get(reverse("dashboard"))

        rows = response.context["stack_health"]
        self.assertEqual([stack for stack, _ in rows], [zed, alpha])
        zed_counts = rows[0][1]
        self.assertEqual((zed_counts.failed, zed_counts.needs_attention, zed_counts.healthy), (0, 1, 0))
        self.assertContains(response, reverse("stack_detail", args=[zed.pk]))

    def test_projects_without_stacks_still_show_health_and_a_hint(self):
        baker.make("app.Project", tenant=self.tenant)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "data-workspace-health")
        self.assertContains(response, "No stacks yet.")


class DashboardCockpitTests(TestCase):
    """The dashboard reads like a cockpit: a headline, instruments that count
    projects (never one grade), warning lights and where they point."""

    def setUp(self):
        self.user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant", name="Acme")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role="owner")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, name="payments-api", owner="platform")
        self.standard = baker.make("app.Standard", tenant=self.tenant, name="Branch protection", enabled=True)
        self.project.standards.add(self.standard)

    def test_a_failing_required_standard_lights_and_points_at_its_project(self):
        check = baker.make("app.CommitCheck", project=self.project, branch=self.project.default_branch, commit_sha="a" * 40)
        baker.make(
            "app.StandardExecution", project=self.project, standard=self.standard, commit_check=check,
            standard_name=self.standard.name, score=0, status="failed", importance="required",
        )
        score_commit(self.project, "a" * 40)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "You're in control.")
        self.assertContains(response, "1 failed.")
        self.assertContains(response, 'data-light="failed" data-lit')
        self.assertContains(response, "1 graded F")
        table = response.content.decode().split("data-light-targets", 1)[1]
        self.assertIn("payments-api", table)
        self.assertIn("platform", table)
        self.assertIn('data-row-tone="failed"', table)

    def test_a_project_never_checked_lights_no_score(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "1 needs attention.")
        self.assertContains(response, 'data-light="no_score" data-lit')
        self.assertNotContains(response, 'data-light="failed" data-lit')
        for gauge in ("health", "checks"):
            self.assertContains(response, f'data-gauge="{gauge}"')
        self.assertContains(response, "data-trend")

    def test_stack_map_links_each_stack(self):
        stack = baker.make("app.Stack", tenant=self.tenant, name="Payments")
        stack.components.add(self.project.components.first() or baker.make("app.Component", tenant=self.tenant, project=self.project))

        response = self.client.get(reverse("dashboard"))

        stack_map = response.content.decode().split("data-stack-map", 1)[1]
        self.assertIn(reverse("stack_detail", args=[stack.pk]), stack_map)

    def test_overview_and_stack_map_are_tabs(self):
        body = self.client.get(reverse("dashboard")).content.decode()

        for tab in ("tab-overview", "tab-map"):
            self.assertIn(f'id="{tab}" role="tabpanel"', body)
