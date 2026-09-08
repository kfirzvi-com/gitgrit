"""is_workspace_admin decides who may manage the active workspace.

Owners and admins qualify through their membership. A superuser qualifies in
every workspace, which is what makes the support view useful. Members and
non-members do not. The one place superuser status does not count is
revealing a connection's stored access token.
"""
import pytest
from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse
from model_bakery import baker

from app.admin import UserAdmin
from app.domain.models import User
from app.workspace_access import (
    ACTIVE_TENANT_KEY,
    SUPPORT_VIEW_STARTED_KEY,
    has_admin_membership,
    is_workspace_admin,
)


def _request(user, tenant):
    request = RequestFactory().get("/")
    request.user = user
    request.tenant = tenant
    return request


@pytest.mark.django_db
class TestIsWorkspaceAdmin(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant", name="Room One", slug="room-one")

    def _user_with_role(self, role):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
        return user

    def test_owner_is_admin(self):
        assert is_workspace_admin(_request(self._user_with_role("owner"), self.tenant))

    def test_admin_is_admin(self):
        assert is_workspace_admin(_request(self._user_with_role("admin"), self.tenant))

    def test_member_is_not_admin(self):
        assert not is_workspace_admin(
            _request(self._user_with_role("member"), self.tenant)
        )

    def test_non_member_is_not_admin(self):
        assert not is_workspace_admin(_request(baker.make("app.User"), self.tenant))

    def test_superuser_is_admin_without_membership(self):
        user = baker.make("app.User", is_superuser=True)
        assert is_workspace_admin(_request(user, self.tenant))

    def test_no_active_workspace_is_never_admin(self):
        user = baker.make("app.User", is_superuser=True)
        assert not is_workspace_admin(_request(user, None))

    def test_has_admin_membership_ignores_superuser(self):
        user = baker.make("app.User", is_superuser=True)
        assert not has_admin_membership(_request(user, self.tenant))
        assert has_admin_membership(_request(self._user_with_role("admin"), self.tenant))


def _login_support(client):
    """A superuser sitting in a workspace they are not a member of."""
    user = baker.make("app.User", is_superuser=True)
    home = baker.make("app.Tenant", name="Home", slug="home")
    baker.make("app.Membership", user=user, tenant=home, role="owner")
    foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
    client.force_login(user)
    client.post(reverse("switch_tenant"), {"tenant_id": foreign.id})
    assert client.session[ACTIVE_TENANT_KEY] == str(foreign.id)
    return user, home, foreign


@pytest.mark.django_db
class TestSupportViewAccess(TestCase):
    def test_superuser_can_invite_in_support_view(self):
        _, _, foreign = _login_support(self.client)
        invitee = baker.make("app.User", email="new@example.com")

        response = self.client.post(
            reverse("invite_member"), {"email": invitee.email, "role": "member"}
        )

        assert response.status_code == 302
        assert foreign.memberships.filter(user=invitee).exists()

    def test_settings_page_treats_superuser_as_admin(self):
        _login_support(self.client)

        response = self.client.get(reverse("tenant_settings"))

        assert response.status_code == 200
        assert response.context["is_admin"] is True
        assert response.context["can_leave"] is False

    def test_reveal_token_denied_in_support_view(self):
        _, _, foreign = _login_support(self.client)
        connection = baker.make(
            "app.PlatformConnection", tenant=foreign, access_token="ghp_secret"
        )

        response = self.client.post(
            reverse("reveal_connection_token", args=[connection.id])
        )

        assert response.status_code == 403
        assert response.json() == {"error": "Not available in support view."}
        assert "ghp_secret" not in response.content.decode()

    def test_reveal_token_still_works_for_real_admin(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant", name="Home", slug="home")
        baker.make("app.Membership", user=user, tenant=tenant, role="admin")
        connection = baker.make(
            "app.PlatformConnection", tenant=tenant, access_token="ghp_secret"
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("reveal_connection_token", args=[connection.id])
        )

        assert response.status_code == 200
        assert response.json() == {"token": "ghp_secret"}

    def test_banner_shows_in_support_view_only(self):
        _, home, foreign = _login_support(self.client)

        html = self.client.get(reverse("dashboard")).content.decode()
        assert 'id="support-view-banner"' in html
        assert foreign.name in html
        assert reverse("leave_support_view") in html

        self.client.post(reverse("switch_tenant"), {"tenant_id": home.id})
        html = self.client.get(reverse("dashboard")).content.decode()
        assert 'id="support-view-banner"' not in html

    def test_banner_absent_for_ordinary_owner(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant", name="Home", slug="home")
        baker.make("app.Membership", user=user, tenant=tenant, role="owner")
        self.client.force_login(user)

        html = self.client.get(reverse("dashboard")).content.decode()

        assert 'id="support-view-banner"' not in html


@pytest.mark.django_db
class TestSwitcherListsEverythingForSuperusers(TestCase):
    url = reverse("workspace_switcher_list")

    def test_superuser_sees_foreign_workspaces_marked_support(self):
        user = baker.make("app.User", is_superuser=True)
        home = baker.make("app.Tenant", name="Home", slug="home")
        baker.make("app.Membership", user=user, tenant=home, role="owner")
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        self.client.force_login(user)

        html = self.client.get(self.url).content.decode()

        assert foreign.name in html
        assert str(foreign.id) in html
        assert "support</span>" in html
        # The user's own row is not marked.
        assert html.count("support</span>") == 1

    def test_superuser_search_finds_foreign_workspaces(self):
        user = baker.make("app.User", is_superuser=True)
        home = baker.make("app.Tenant", name="Home", slug="home")
        baker.make("app.Membership", user=user, tenant=home, role="owner")
        baker.make("app.Tenant", name="Secret Client", slug="secret-client")
        self.client.force_login(user)

        html = self.client.get(self.url, {"q": "secret"}).content.decode()

        assert "Secret Client" in html

    def test_superuser_workspace_count_covers_all_workspaces(self):
        user = baker.make("app.User", is_superuser=True)
        home = baker.make("app.Tenant", name="Home", slug="home")
        baker.make("app.Membership", user=user, tenant=home, role="owner")
        baker.make("app.Tenant", _quantity=6)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        assert response.context["workspace_count"] == 7
        assert response.context["show_workspace_search"] is True


class TestUserAdminShowsSuperuser(TestCase):
    def test_is_superuser_in_list_display_and_filter(self):
        user_admin = UserAdmin(User, admin.site)
        assert "is_superuser" in user_admin.list_display
        assert "is_superuser" in user_admin.list_filter
