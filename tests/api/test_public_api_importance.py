"""Setting an attached standard's importance through the public API."""
from model_bakery import baker

from app.domain.models import ProjectStandard
from tests.api.test_public_api import PublicAPITestCase


class TestSetImportance(PublicAPITestCase):
    def setUp(self):
        super().setUp()
        self.project = baker.make("app.Project", tenant=self.tenant)
        self.standard = baker.make("app.Standard", tenant=self.tenant, name="No secrets")
        self.project.standards.add(self.standard)
        self.url = f"{self.ws}/projects/{self.project.id}/standards/{self.standard.id}/"

    def test_sets_and_returns_the_importance(self):
        r = self.send("patch", self.url, {"importance": "required"})

        assert r.status_code == 200
        assert r.json() == {
            "id": str(self.standard.id),
            "name": "No secrets",
            "importance": "required",
        }
        assert ProjectStandard.objects.get(project=self.project).importance == "required"

    def test_an_unknown_importance_is_400_and_changes_nothing(self):
        r = self.send("patch", self.url, {"importance": "critical"})

        assert r.status_code == 400
        assert ProjectStandard.objects.get(project=self.project).importance == "major"

    def test_a_standard_not_attached_is_404(self):
        other = baker.make("app.Standard", tenant=self.tenant)

        r = self.send(
            "patch",
            f"{self.ws}/projects/{self.project.id}/standards/{other.id}/",
            {"importance": "minor"},
        )

        assert r.status_code == 404

    def test_a_project_of_another_workspace_is_404(self):
        foreign = baker.make("app.Project", tenant=baker.make("app.Tenant"))

        r = self.send(
            "patch",
            f"{self.ws}/projects/{foreign.id}/standards/{self.standard.id}/",
            {"importance": "minor"},
        )

        assert r.status_code == 404

    def test_the_list_shows_the_new_importance(self):
        self.standard.enabled, self.standard.draft, self.standard.criteria = True, False, {}
        self.standard.save()
        self.send("patch", self.url, {"importance": "minor"})

        r = self.get(f"{self.ws}/projects/{self.project.id}/standards/")

        assert [s["importance"] for s in r.json()] == ["minor"]
