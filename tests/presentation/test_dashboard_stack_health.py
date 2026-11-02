"""The dashboard shows the workspace's project health and each stack's,
worst first."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker


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
