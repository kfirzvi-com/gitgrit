"""A workspace picks how commit scores read: letters (the default) or
numbers. Health, colours and the API's numbers do not change, and each
standard's own result is always a number."""
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import StandardExecution
from app.domain.score_representation import ScoreDisplay
from tests.support import score_commit

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class ScoreDisplaySettingTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.user = baker.make("app.User")
        self.membership = baker.make("app.Membership", user=self.user, tenant=self.tenant, role="owner")
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        standard = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(standard)
        check = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha="a" * 40)
        baker.make(
            "app.StandardExecution", project=self.project, standard=standard, standard_name=standard.name,
            status=StandardExecution.Status.PASSED, score=82, commit_check=check,
        )
        score_commit(self.project, "a" * 40)

    def test_letters_by_default(self):
        assert self.tenant.score_display == ScoreDisplay.LETTERS
        body = self.client.get(reverse("project_list")).content.decode()
        assert ">B</span>" in body

    def test_an_admin_switches_to_numbers_in_place(self):
        response = self.client.post(reverse("set_score_display"), {"score_display": "numbers"}, HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        assert "toast" in response["HX-Trigger"]
        self.tenant.refresh_from_db()
        assert self.tenant.score_display == ScoreDisplay.NUMBERS
        body = self.client.get(reverse("project_list")).content.decode()
        assert ">82</span>" in body
        svg = self.client.get(reverse("project_badge", args=[self.project.pk])).content.decode()
        assert "GitGrit compliance: 82" in svg

    def test_a_member_cannot_change_it(self):
        member = baker.make("app.User")
        baker.make("app.Membership", user=member, tenant=self.tenant, role="member")
        self.client.force_login(member)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

        self.client.post(reverse("set_score_display"), {"score_display": "numbers"}, HTTP_HX_REQUEST="true")

        self.tenant.refresh_from_db()
        assert self.tenant.score_display == ScoreDisplay.LETTERS

    def test_an_unknown_choice_changes_nothing(self):
        self.client.post(reverse("set_score_display"), {"score_display": "emoji"}, HTTP_HX_REQUEST="true")

        self.tenant.refresh_from_db()
        assert self.tenant.score_display == ScoreDisplay.LETTERS
