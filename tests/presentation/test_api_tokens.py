"""Creating and revoking API tokens: personal ones on the profile page,
workspace ones (admins only) on the workspace settings page."""
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import APIToken


class TokenPageTestCase(TestCase):
    def login(self, role="owner"):
        self.user = baker.make("app.User", email="dev@example.com")
        self.tenant = baker.make("app.Tenant", name="Acme")
        baker.make("app.Membership", user=self.user, tenant=self.tenant, role=role)
        self.client.force_login(self.user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()


class PersonalTokenTests(TokenPageTestCase):
    def setUp(self):
        self.login(role="member")

    def test_create_shows_the_token_once(self):
        r = self.client.post(reverse("create_personal_token"), {"token_name": "laptop"}, follow=True)
        token = APIToken.objects.get()
        assert (token.kind, token.user, token.tenant) == ("personal", self.user, None)
        content = r.content.decode()
        assert 'value="grit_pat_' in content
        assert "laptop" in content
        again = self.client.get(reverse("profile")).content.decode()
        assert 'value="grit_pat_' not in again

    def test_name_required(self):
        self.client.post(reverse("create_personal_token"), {"token_name": "  "})
        assert not APIToken.objects.exists()

    def test_profile_lists_only_my_personal_tokens(self):
        mine, _ = APIToken.issue(name="mine", created_by=self.user, user=self.user)
        APIToken.issue(name="theirs", created_by=self.user, user=baker.make("app.User"))
        APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        assert list(self.client.get(reverse("profile")).context["api_tokens"]) == [mine]

    def test_revoke_mine(self):
        token, _ = APIToken.issue(name="mine", created_by=self.user, user=self.user)
        self.client.post(reverse("revoke_personal_token", args=[token.id]))
        assert not APIToken.objects.exists()

    def test_cannot_revoke_someone_elses(self):
        token, _ = APIToken.issue(name="theirs", created_by=self.user, user=baker.make("app.User"))
        r = self.client.post(reverse("revoke_personal_token", args=[token.id]))
        assert r.status_code == 404
        assert APIToken.objects.filter(id=token.id).exists()


class WorkspaceTokenTests(TokenPageTestCase):
    def test_admin_creates_and_sees_it_once(self):
        self.login(role="admin")
        r = self.client.post(reverse("create_workspace_token"), {"token_name": "GitHub Actions"})
        assert r["Location"].endswith("#section-api-tokens")
        token = APIToken.objects.get()
        assert (token.kind, token.user, token.tenant, token.created_by) == (
            "workspace", None, self.tenant, self.user,
        )
        page = self.client.get(reverse("tenant_settings"))
        assert 'value="grit_ws_' in page.content.decode()
        assert list(page.context["workspace_tokens"]) == [token]
        assert 'value="grit_ws_' not in self.client.get(reverse("tenant_settings")).content.decode()

    def test_member_cannot_create_or_see_them(self):
        self.login(role="member")
        self.client.post(reverse("create_workspace_token"), {"token_name": "sneaky"})
        assert not APIToken.objects.exists()
        page = self.client.get(reverse("tenant_settings"))
        assert "workspace_tokens" not in page.context
        assert "section-api-tokens" not in page.content.decode()

    def test_member_cannot_revoke(self):
        self.login(role="member")
        token, _ = APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        self.client.post(reverse("revoke_workspace_token", args=[token.id]))
        assert APIToken.objects.filter(id=token.id).exists()

    def test_admin_revokes_only_in_own_workspace(self):
        self.login(role="owner")
        mine, _ = APIToken.issue(name="ci", created_by=self.user, tenant=self.tenant)
        other, _ = APIToken.issue(name="ci", created_by=self.user, tenant=baker.make("app.Tenant"))
        assert self.client.post(reverse("revoke_workspace_token", args=[other.id])).status_code == 404
        self.client.post(reverse("revoke_workspace_token", args=[mine.id]))
        assert list(APIToken.objects.all()) == [other]
