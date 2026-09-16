"""Activation via the enable toggle is a coverage change: flipping a standard
to runnable queues it to re-run on its linked projects; flipping it off queues
nothing. The background job's ``defer`` is mocked — no sandbox."""
from unittest import mock

import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import StandardExecution
from tests.support import running_executions


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
    return mock.patch("app.application.standard_runs.run_standards.configure")



@pytest.mark.django_db
class ToggleStandardTriggersRunsTests(TestCase):
    def _toggle(self, standard):
        with _run_patch() as configure:
            resp = self.client.post(reverse("toggle_standard", args=[standard.pk]))
        assert resp.status_code == 302
        return configure

    def test_enabling_queues_on_linked_projects(self):
        _, tenant = _login_member(self.client)
        standard = baker.make("app.Standard", tenant=tenant, enabled=False, draft=False)
        project = baker.make("app.Project", tenant=tenant)
        project.standards.add(standard)

        configure = self._toggle(standard)

        standard.refresh_from_db()
        assert standard.enabled is True
        configure.assert_called_once_with(lock=f"standards:{project.pk}")
        row = running_executions(project).get()
        assert row.standard_id == standard.pk
        assert row.triggered_by == "activated"

    def test_disabling_queues_nothing(self):
        _, tenant = _login_member(self.client)
        standard = baker.make("app.Standard", tenant=tenant, enabled=True, draft=False)
        project = baker.make("app.Project", tenant=tenant)
        project.standards.add(standard)

        configure = self._toggle(standard)

        standard.refresh_from_db()
        assert standard.enabled is False
        configure.assert_not_called()
        assert not running_executions(project).exists()

    def test_toggling_a_draft_refuses_and_queues_nothing(self):
        # Drafts never run, so a draft can only be disabled — the toggle
        # refuses to enable it rather than enabling a standard that won't run.
        _, tenant = _login_member(self.client)
        standard = baker.make("app.Standard", tenant=tenant, enabled=False, draft=True)
        project = baker.make("app.Project", tenant=tenant)
        project.standards.add(standard)

        configure = self._toggle(standard)

        standard.refresh_from_db()
        assert standard.enabled is False
        configure.assert_not_called()
        assert not running_executions(project).exists()
