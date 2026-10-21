"""Setting importance while attaching standards: given importances are
written, attached standards that stay keep theirs, detaching and attaching
again starts over at Major, and an unknown value is rejected before anything
changes."""
from django.test import TestCase
from model_bakery import baker

from app.application import project_management
from app.domain.importance import UnknownImportance
from app.domain.models import ProjectStandard
from tests.support import defer_patch


class SetProjectStandardsImportanceTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.a, self.b = (
            baker.make("app.Standard", tenant=self.tenant, enabled=False) for _ in range(2)
        )

    def _importances(self):
        return dict(
            ProjectStandard.objects.filter(project=self.project).values_list(
                "standard_id", "importance"
            )
        )

    def test_writes_the_given_importances(self):
        project_management.set_project_standards(
            self.project, [self.a.pk, self.b.pk], importances={str(self.a.pk): "Required"}
        )

        assert self._importances() == {self.a.pk: "required", self.b.pk: "major"}

    def test_attached_standards_that_stay_keep_their_importance(self):
        project_management.set_project_standards(
            self.project, [self.a.pk], importances={str(self.a.pk): "minor"}
        )
        project_management.set_project_standards(self.project, [self.a.pk, self.b.pk])

        assert self._importances() == {self.a.pk: "minor", self.b.pk: "major"}

    def test_detaching_and_attaching_again_starts_over_at_major(self):
        project_management.set_project_standards(
            self.project, [self.a.pk], importances={str(self.a.pk): "required"}
        )
        project_management.set_project_standards(self.project, [])
        project_management.set_project_standards(self.project, [self.a.pk])

        assert self._importances() == {self.a.pk: "major"}

    def test_an_unknown_importance_changes_nothing(self):
        project_management.set_project_standards(self.project, [self.a.pk])

        with self.assertRaises(UnknownImportance):
            project_management.set_project_standards(
                self.project, [self.b.pk], importances={str(self.b.pk): "critical"}
            )

        assert self._importances() == {self.a.pk: "major"}

    def test_attach_and_detach_keep_the_others_importance(self):
        project_management.set_project_standards(
            self.project, [self.a.pk], importances={str(self.a.pk): "required"}
        )
        with defer_patch():
            project_management.attach_standards(self.project, [self.b.pk])
        project_management.detach_standards(self.project, [self.b.pk])

        assert self._importances() == {self.a.pk: "required"}

    def test_an_id_that_is_not_a_uuid_is_ignored(self):
        project_management.set_project_standards(
            self.project, [self.a.pk], importances={"not-a-uuid": "minor"}
        )

        assert self._importances() == {self.a.pk: "major"}
