"""Importance: how much an attached standard matters to one project.
Required, Major and Minor, most important first; every attached standard
starts at Major; a value that names no importance is rejected, never read as
the default; and importance lives on the attachment, so the same standard
can matter differently to two projects."""
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from model_bakery import baker

from app.domain import importance
from app.domain.importance import Importance, UnknownImportance
from app.domain.models import ProjectStandard


class ImportanceValueTests(SimpleTestCase):
    def test_most_important_first(self):
        assert importance.choices() == [
            ("required", "Required"),
            ("major", "Major"),
            ("minor", "Minor"),
        ]

    def test_major_is_the_default(self):
        assert importance.DEFAULT is Importance.MAJOR

    def test_values_fit_the_model_field(self):
        assert all(len(i.value) <= importance.MAX_LENGTH for i in Importance)

    def test_parse_ignores_case_and_spaces(self):
        assert importance.parse(" Required ") is Importance.REQUIRED

    def test_parse_rejects_an_unknown_value(self):
        with self.assertRaises(UnknownImportance) as raised:
            importance.parse("critical")
        assert "required, major, minor" in str(raised.exception)


class AttachedStandardImportanceTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.standard = baker.make("app.Standard", tenant=self.tenant)

    def test_an_attached_standard_starts_at_major(self):
        self.project.standards.add(self.standard)

        attachment = ProjectStandard.objects.get(project=self.project)
        assert attachment.importance == "major"

    def test_the_same_standard_can_matter_differently_to_two_projects(self):
        other = baker.make("app.Project", tenant=self.tenant)
        self.project.standards.add(self.standard)
        other.standards.add(self.standard)

        ProjectStandard.set_importances(self.project, {self.standard.pk: Importance.REQUIRED})

        assert ProjectStandard.objects.get(project=self.project).importance == "required"
        assert ProjectStandard.objects.get(project=other).importance == "major"

    def test_setting_the_importance_of_an_unattached_standard_does_nothing(self):
        ProjectStandard.set_importances(self.project, {self.standard.pk: Importance.MINOR})

        assert not ProjectStandard.objects.filter(project=self.project).exists()

    def test_the_database_rejects_an_unknown_importance(self):
        self.project.standards.add(self.standard)

        with self.assertRaises(IntegrityError), transaction.atomic():
            ProjectStandard.objects.filter(project=self.project).update(importance="critical")
