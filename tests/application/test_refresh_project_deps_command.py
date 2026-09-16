from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from model_bakery import baker

from app.application import dependency_agent as da
from app.domain.models import Project


class RefreshProjectDepsSyncTests(TestCase):
    def _project(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        return baker.make("app.Project", tenant=tenant, platform_connection=conn, name="web")

    def test_sync_success_reports_counts_and_keeps_ok_status(self):
        """Regression: the success line read ``result.external``, a field that
        does not exist, so every successful --sync run was recorded FAILED."""
        project = self._project()
        result = da.DependencyResult(
            internal=[{"target": "org/api"}],
            external_providers=[{"name": "Stripe"}],
            external_consumers=[{"name": "Partner"}],
        )

        def fake_infer(p):
            Project.objects.filter(pk=p.pk).update(deps_status=Project.DepsStatus.OK)
            return result

        out, err = StringIO(), StringIO()
        with patch.object(da, "infer_and_store", fake_infer):
            call_command("refresh_project_deps", str(project.id), "--sync", stdout=out, stderr=err)

        project.refresh_from_db()
        self.assertEqual(project.deps_status, Project.DepsStatus.OK, err.getvalue())
        self.assertIn("web: 1 internal, 2 external", out.getvalue())
        self.assertEqual(err.getvalue(), "")

    def test_sync_failure_marks_project_failed(self):
        project = self._project()

        def boom(p):
            raise RuntimeError("provider said no")

        out, err = StringIO(), StringIO()
        with patch.object(da, "infer_and_store", boom):
            call_command("refresh_project_deps", str(project.id), "--sync", stdout=out, stderr=err)

        project.refresh_from_db()
        self.assertEqual(project.deps_status, Project.DepsStatus.FAILED)
        self.assertIn("provider said no", project.deps_error)
        self.assertIn("provider said no", err.getvalue())
