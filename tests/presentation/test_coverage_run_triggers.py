"""Activation via the enable toggle is a coverage change: flipping a standard
to runnable re-runs it on its linked projects; flipping it off runs nothing."""
from unittest import mock

import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker


def _login_member(client):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


def _run_patch():
    return mock.patch(
        "app.application.standard_engine.StandardEngine.run_for_project",
        return_value=[{"passed": True, "details": {}}],
    )


@pytest.mark.django_db
class ToggleStandardTriggersRunsTests(TestCase):
    def _toggle(self, standard):
        with _run_patch() as run:
            resp = self.client.post(reverse("toggle_standard", args=[standard.pk]))
        assert resp.status_code == 302
        return run

    def test_enabling_runs_on_linked_projects(self):
        _, tenant = _login_member(self.client)
        standard = baker.make("app.Standard", tenant=tenant, enabled=False, draft=False)
        project = baker.make("app.Project", tenant=tenant)
        project.standards.add(standard)

        run = self._toggle(standard)

        standard.refresh_from_db()
        assert standard.enabled is True
        run.assert_called_once_with(project, [standard])

    def test_disabling_runs_nothing(self):
        _, tenant = _login_member(self.client)
        standard = baker.make("app.Standard", tenant=tenant, enabled=True, draft=False)
        project = baker.make("app.Project", tenant=tenant)
        project.standards.add(standard)

        run = self._toggle(standard)

        standard.refresh_from_db()
        assert standard.enabled is False
        run.assert_not_called()

    def test_enabling_a_draft_runs_nothing(self):
        _, tenant = _login_member(self.client)
        standard = baker.make("app.Standard", tenant=tenant, enabled=False, draft=True)
        project = baker.make("app.Project", tenant=tenant)
        project.standards.add(standard)

        run = self._toggle(standard)

        standard.refresh_from_db()
        assert standard.enabled is True
        run.assert_not_called()
