"""The save choke point: every mutation through ``create_standard_version``
queues a runnable standard to re-run on its linked projects.

This is the seam the MCP tools (``update_standard``/``set_standard_code``)
and the web forms share — proving it here proves the 18 July scenario
(standards seeded through ``StandardService``, nothing ever ran) can't recur.
"""

import pytest
from django.test import TestCase
from model_bakery import baker

from app.application.standard_service import StandardService
from app.domain.models import StandardExecution
from tests.support import defer_patch


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

    def _running(self):
        return StandardExecution.objects.filter(
            project=self.project, status=StandardExecution.Status.RUNNING
        )

    def test_update_queues_on_linked_projects_and_reports(self):
        standard = self._standard()

        with defer_patch() as configure:
            result = self.service.update_standard(
                self.tenant, self.user, str(standard.pk), {"description": "new"}
            )

        configure.assert_called_once_with(lock=f"standards:{self.project.pk}")
        assert [r.standard_id for r in self._running()] == [standard.pk]
        assert result["updated"] is True
        assert result["runs"]["queued"] == 1
        assert result["runs"]["projects"] == 1

    def test_updating_a_draft_queues_nothing(self):
        standard = self._standard(draft=True)

        with defer_patch() as configure:
            result = self.service.update_standard(
                self.tenant, self.user, str(standard.pk), {"description": "new"}
            )

        configure.assert_not_called()
        assert not self._running().exists()
        assert "runs" not in result

    def test_publishing_a_draft_queues_it(self):
        standard = self._standard(draft=True)

        with defer_patch() as configure:
            result = self.service.update_standard(
                self.tenant, self.user, str(standard.pk), {"draft": False}
            )

        configure.assert_called_once()
        assert result["runs"]["queued"] == 1

    def test_create_has_no_linked_projects_so_nothing_is_queued(self):
        with defer_patch() as configure:
            result = self.service.create_standard(
                self.tenant, self.user, {"name": "Fresh"}
            )

        configure.assert_not_called()
        assert "runs" not in result

    def test_enqueue_failure_never_fails_the_save(self):
        standard = self._standard()

        with defer_patch(side_effect=RuntimeError("queue down")):
            result = self.service.update_standard(
                self.tenant, self.user, str(standard.pk), {"description": "new"}
            )

        standard.refresh_from_db()
        assert standard.description == "new"
        assert result["updated"] is True
        assert "runs" not in result
