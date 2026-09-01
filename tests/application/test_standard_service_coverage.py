"""The save choke point: every mutation through ``create_standard_version``
re-runs a runnable standard on its linked projects.

This is the seam the MCP tools (``update_standard``/``set_standard_code``)
and the web forms share — proving it here proves the 18 July scenario
(standards seeded through ``StandardService``, nothing ever ran) can't recur.
"""
from unittest import mock

import pytest
from django.test import TestCase
from model_bakery import baker

from app.application.standard_service import StandardService

PASSED = {"passed": True, "score": 100, "message": "OK", "details": {}}


def _run_patch(**kwargs):
    return mock.patch(
        "app.application.standard_engine.StandardEngine.run_for_project", **kwargs
    )


@pytest.mark.django_db
class SaveTriggersCoverageRunTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.user = baker.make("app.User")
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.service = StandardService()

    def _standard(self, **kw):
        kw.setdefault("enabled", True)
        kw.setdefault("draft", False)
        standard = baker.make("app.Standard", tenant=self.tenant, **kw)
        self.project.standards.add(standard)
        return standard

    def test_update_runs_on_linked_projects_and_reports(self):
        standard = self._standard()

        with _run_patch(return_value=[PASSED]) as run:
            result = self.service.update_standard(
                self.tenant, self.user, str(standard.pk), {"description": "new"}
            )

        run.assert_called_once_with(self.project, [standard])
        assert result["updated"] is True
        assert result["runs"]["ran"] == 1
        assert result["runs"]["passed"] == 1

    def test_updating_a_draft_runs_nothing(self):
        standard = self._standard(draft=True)

        with _run_patch(return_value=[PASSED]) as run:
            result = self.service.update_standard(
                self.tenant, self.user, str(standard.pk), {"description": "new"}
            )

        run.assert_not_called()
        assert "runs" not in result

    def test_publishing_a_draft_runs_it(self):
        standard = self._standard(draft=True)

        with _run_patch(return_value=[PASSED]) as run:
            result = self.service.update_standard(
                self.tenant, self.user, str(standard.pk), {"draft": False}
            )

        run.assert_called_once()
        assert result["runs"]["ran"] == 1

    def test_create_has_no_linked_projects_so_nothing_runs(self):
        with _run_patch(return_value=[PASSED]) as run:
            result = self.service.create_standard(
                self.tenant, self.user, {"name": "Fresh"}
            )

        run.assert_not_called()
        assert "runs" not in result

    def test_engine_failure_never_fails_the_save(self):
        standard = self._standard()

        with _run_patch(side_effect=RuntimeError("sandbox down")):
            result = self.service.update_standard(
                self.tenant, self.user, str(standard.pk), {"description": "new"}
            )

        standard.refresh_from_db()
        assert standard.description == "new"
        assert result["updated"] is True
        assert "runs" not in result
