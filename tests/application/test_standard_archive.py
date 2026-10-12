"""Deleting a standard archives it: it disappears from the workspace and its
projects, but past runs keep their standard and the version they ran."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application.commit_checks import commit_results
from app.application.errors import NotFoundError
from app.application.standard_service import StandardService
from app.domain.models import Standard, StandardExecution

Status = StandardExecution.Status
SHA = "a" * 40


class ArchiveTestCase(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self.standard = baker.make("app.Standard", tenant=self.tenant, name="Pinned CI", code="v1 code")
        self.project.standards.add(self.standard)
        self.version = baker.make("app.StandardVersion", standard=self.standard, version=1, code="v1 code")
        self.check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha=SHA)
        self.run = self._result(self.standard, Status.FAILED)

    def _result(self, standard, status, name=None):
        return baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=name or standard.name, standard_version=self.version if standard else None,
            status=status, commit_check=self.check,
        )


class ArchiveTests(ArchiveTestCase):
    def test_archive_hides_it_and_detaches_it(self):
        self.standard.archive()

        assert not Standard.objects.filter(pk=self.standard.pk).exists()
        assert Standard.all_objects.get(pk=self.standard.pk).archived_at is not None
        assert list(self.project.standards.all()) == []
        assert list(self.tenant.standards.all()) == []

    def test_past_runs_keep_the_standard_and_the_version_they_ran(self):
        StandardService().delete_standard(self.tenant, str(self.standard.pk))

        self.run.refresh_from_db()
        assert self.run.standard_id == self.standard.pk
        assert self.run.standard_version.code == "v1 code"

    def test_an_archived_standard_is_not_found_again(self):
        self.standard.archive()
        with self.assertRaises(NotFoundError):
            StandardService().delete_standard(self.tenant, str(self.standard.pk))

    def test_the_delete_button_archives(self):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

        self.client.post(reverse("delete_standard", args=[self.standard.pk]))

        assert Standard.all_objects.get(pk=self.standard.pk).archived_at is not None
        self.run.refresh_from_db()
        assert self.run.standard_version_id == self.version.pk


class CommitResultsTests(ArchiveTestCase):
    def test_a_commit_still_shows_an_archived_standards_result(self):
        self.standard.archive()

        [result] = commit_results(self.project, SHA).results

        assert result.pk == self.run.pk
        assert result.still_attached is False

    def test_runs_of_standards_deleted_before_archiving_each_show(self):
        a = self._result(None, Status.PASSED, name="Gone A")
        b = self._result(None, Status.FAILED, name="Gone B")

        results = commit_results(self.project, SHA).results

        assert {r.pk for r in results} == {self.run.pk, a.pk, b.pk}
