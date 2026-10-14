"""Workspaces are gated: only superusers create them, owners and superusers
delete them (typing the name back), and a signed-in user in no workspace is
sent to the no-workspace page."""
import json
from unittest import mock

import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import Membership, Project, Tenant


def _login(client, user, tenant=None):
    client.force_login(user)
    if tenant is not None:
        session = client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()


@pytest.mark.django_db
class TestCreateWorkspace(TestCase):
    url = reverse("create_tenant")

    def setUp(self):
        self.admin = baker.make("app.User", is_superuser=True, email="root@example.com")
        _login(self.client, self.admin)

    def test_superuser_names_another_user_as_owner(self):
        owner = baker.make("app.User", email="ada@acme.example")

        response = self.client.post(
            self.url, {"name": "Acme Corp", "owner_email": "ADA@acme.example"}
        )

        assert response.headers["Location"] == reverse("dashboard")
        tenant = Tenant.objects.get(name="Acme Corp")
        assert tenant.slug == "acme-corp"
        membership = Membership.objects.get(tenant=tenant)
        assert (membership.user, membership.role) == (owner, "owner")
        # The superuser isn't added; they look in through the support view.
        assert self.client.session["active_tenant_id"] == str(tenant.pk)
        assert "support_view_started_at" in self.client.session

    def test_superuser_can_own_it_themselves(self):
        self.client.post(self.url, {"name": "Acme Corp", "owner_email": "root@example.com"})

        tenant = Tenant.objects.get(name="Acme Corp")
        assert Membership.objects.get(tenant=tenant).user == self.admin
        assert "support_view_started_at" not in self.client.session

    def test_owner_is_required(self):
        response = self.client.post(self.url, {"name": "Acme Corp", "owner_email": ""})

        assert response.status_code == 200
        assert b"Every workspace needs an owner." in response.content
        assert not Tenant.objects.filter(name="Acme Corp").exists()

    def test_owner_prefilled_for_an_admin_without_a_workspace(self):
        assert b'value="root@example.com"' in self.client.get(self.url).content

    def test_owner_must_be_an_active_user(self):
        baker.make("app.User", email="pending@acme.example", is_active=False)
        for email in ("nobody@acme.example", "pending@acme.example"):
            with self.subTest(email=email):
                response = self.client.post(
                    self.url, {"name": "Acme Corp", "owner_email": email}
                )
                assert response.status_code == 200
                assert b"No active user with that email" in response.content
        assert not Tenant.objects.filter(name="Acme Corp").exists()

    def test_owner_suggestions_list_active_users(self):
        baker.make("app.User", email="ada@acme.example")
        baker.make("app.User", email="pending@acme.example", is_active=False)

        html = self.client.get(self.url).content.decode()

        assert '<option value="ada@acme.example">' in html
        assert "pending@acme.example" not in html

    def test_workspace_owner_cannot_create_one(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="owner")
        _login(self.client, user, tenant)

        assert self.client.get(self.url).status_code == 403
        assert self.client.post(self.url, {"name": "Mine"}).status_code == 403
        assert not Tenant.objects.filter(name="Mine").exists()

    def test_new_workspace_link_only_for_superusers(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="owner")
        _login(self.client, user, tenant)

        assert b"+ New Workspace" not in self.client.get(reverse("dashboard")).content


@pytest.mark.django_db
class TestDeleteWorkspace(TestCase):
    url = reverse("delete_workspace")

    def setUp(self):
        self.tenant = baker.make("app.Tenant", name="Acme Corp")
        self.owner = baker.make("app.User")
        baker.make("app.Membership", user=self.owner, tenant=self.tenant, role="owner")

    def _delete(self, user, typed="Acme Corp"):
        _login(self.client, user, self.tenant)
        with mock.patch("app.application.workspace_service.get_platform_client") as client:
            response = self.client.post(self.url, {"confirm_name": typed})
        return response, client

    def test_owner_deletes_with_the_exact_name(self):
        response, _ = self._delete(self.owner)

        assert response.headers["Location"] == reverse("dashboard")
        assert not Tenant.objects.filter(pk=self.tenant.pk).exists()
        assert "active_tenant_id" not in self.client.session

    def test_wrong_name_deletes_nothing(self):
        for typed in ("", "acme corp", "Acme", "Acme Corp "):
            with self.subTest(typed=typed):
                response, _ = self._delete(self.owner, typed=typed)
                assert response.status_code == 302
                assert Tenant.objects.filter(pk=self.tenant.pk).exists()

    def test_admins_and_members_cannot_delete(self):
        for role in ("admin", "member"):
            with self.subTest(role=role):
                user = baker.make("app.User")
                baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
                response, _ = self._delete(user)
                assert response.status_code == 403
                assert Tenant.objects.filter(pk=self.tenant.pk).exists()

    def test_superuser_can_delete_from_the_support_view(self):
        admin = baker.make("app.User", is_superuser=True)
        _login(self.client, admin)
        self.client.post(reverse("switch_tenant"), {"tenant_id": str(self.tenant.pk)})

        with mock.patch("app.application.workspace_service.get_platform_client"):
            self.client.post(self.url, {"confirm_name": "Acme Corp"})

        assert not Tenant.objects.filter(pk=self.tenant.pk).exists()

    def test_removes_project_webhooks_and_survives_a_failing_one(self):
        connection = baker.make("app.PlatformConnection", tenant=self.tenant)
        ok = baker.make(Project, tenant=self.tenant, platform_connection=connection,
                        external_id="org/ok", webhook_id="1")
        baker.make(Project, tenant=self.tenant, platform_connection=connection,
                   external_id="org/gone", webhook_id="2")
        baker.make(Project, tenant=self.tenant, platform_connection=connection,
                   external_id="org/none", webhook_id="")
        _login(self.client, self.owner, self.tenant)

        with mock.patch("app.application.workspace_service.get_platform_client") as factory:
            factory.return_value.delete_webhook.side_effect = [None, RuntimeError("404")]
            self.client.post(self.url, {"confirm_name": "Acme Corp"})

        calls = sorted(c.args for c in factory.return_value.delete_webhook.call_args_list)
        assert calls == [("org/gone", "2"), ("org/ok", "1")]
        assert not Tenant.objects.filter(pk=self.tenant.pk).exists()
        assert not Project.objects.filter(pk=ok.pk).exists()

    def test_danger_zone_shown_to_owners_only(self):
        _login(self.client, self.owner, self.tenant)
        assert b"Danger Zone" in self.client.get(reverse("tenant_settings")).content

        member = baker.make("app.User")
        baker.make("app.Membership", user=member, tenant=self.tenant, role="admin")
        _login(self.client, member, self.tenant)
        assert b"Danger Zone" not in self.client.get(reverse("tenant_settings")).content


@pytest.mark.django_db
class TestNoWorkspace(TestCase):
    def test_workspace_pages_redirect_to_the_no_workspace_page(self):
        _login(self.client, baker.make("app.User"))

        for name in ("dashboard", "project_list", "tenant_settings"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                assert response.headers["Location"] == reverse("no_workspace")

    def test_no_workspace_page_and_profile_still_work(self):
        _login(self.client, baker.make("app.User"))

        assert b"No workspace yet" in self.client.get(reverse("no_workspace")).content
        assert self.client.get(reverse("profile")).status_code == 200

    def test_superuser_is_offered_to_create_or_open_one(self):
        baker.make("app.Tenant", name="Initech")
        _login(self.client, baker.make("app.User", is_superuser=True))

        html = self.client.get(reverse("no_workspace")).content.decode()

        assert reverse("create_tenant") in html
        assert "Initech" in html

    def test_member_of_a_workspace_skips_it(self):
        user = baker.make("app.User")
        baker.make("app.Membership", user=user)
        _login(self.client, user)

        assert self.client.get(reverse("no_workspace")).headers["Location"] == reverse("dashboard")


@pytest.mark.django_db
class TestMemberRoles(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.owner = baker.make("app.Membership", tenant=self.tenant, role="owner")
        self.admin = baker.make("app.Membership", tenant=self.tenant, role="admin")
        self.member = baker.make("app.Membership", tenant=self.tenant, role="member")

    def _settings_html(self, membership):
        _login(self.client, membership.user, self.tenant)
        return self.client.get(reverse("tenant_settings")).content.decode()

    def _role_url(self, membership):
        return reverse("change_member_role", args=[membership.pk])

    def test_owner_gets_a_dropdown_except_on_the_last_owner(self):
        html = self._settings_html(self.owner)

        assert self._role_url(self.admin) in html
        assert self._role_url(self.member) in html
        assert self._role_url(self.owner) not in html
        assert 'value="owner"' in html
        assert reverse("remove_member", args=[self.owner.pk]) not in html

    def test_admin_dropdown_has_no_owner_option(self):
        html = self._settings_html(self.admin)

        assert self._role_url(self.member) in html
        assert self._role_url(self.owner) not in html
        assert '<option value="owner"' not in html

    def test_member_sees_no_dropdown(self):
        assert "change_member_role" not in self._settings_html(self.member)
        assert self._role_url(self.admin) not in self._settings_html(self.member)

    def test_change_role(self):
        _login(self.client, self.owner.user, self.tenant)

        response = self.client.post(self._role_url(self.member), {"role": "owner"})

        assert response.headers["Location"].endswith("#section-members")
        assert Membership.objects.get(pk=self.member.pk).role == "owner"

    def test_refusals_change_nothing(self):
        _login(self.client, self.admin.user, self.tenant)
        self.client.post(self._role_url(self.member), {"role": "owner"})
        _login(self.client, self.owner.user, self.tenant)
        self.client.post(self._role_url(self.owner), {"role": "member"})

        assert Membership.objects.get(pk=self.member.pk).role == "member"
        assert Membership.objects.get(pk=self.owner.pk).role == "owner"

    def test_owner_removes_a_second_owner(self):
        second = baker.make("app.Membership", tenant=self.tenant, role="owner")
        _login(self.client, self.owner.user, self.tenant)

        self.client.post(reverse("remove_member", args=[second.pk]))

        assert not Membership.objects.filter(pk=second.pk).exists()

    def test_only_the_last_owner_is_told_they_cannot_leave(self):
        message = "You're the only owner"
        assert message in self._settings_html(self.owner)
        assert message not in self._settings_html(self.member)
        root = baker.make("app.User", is_superuser=True)
        _login(self.client, root)
        self.client.post(reverse("switch_tenant"), {"tenant_id": str(self.tenant.pk)})
        assert message not in self.client.get(reverse("tenant_settings")).content.decode()

    def test_rows_say_who_granted_the_role(self):
        granter = baker.make("app.User", email="granter@example.com")
        Membership.objects.filter(pk=self.member.pk).update(granted_by=granter)

        html = self._settings_html(self.owner)

        assert "Access granted" in html
        assert "by granter@example.com" in html


@pytest.mark.django_db
class TestMemberActionsInPlace(TestCase):
    """Over HTMX, member actions redraw the member panel and toast; the page
    reloads only when the change takes it away or changes what you may do."""

    HTMX = {"HTTP_HX_REQUEST": "true"}

    def setUp(self):
        self.tenant = baker.make("app.Tenant", name="Acme")
        self.owner = baker.make("app.Membership", tenant=self.tenant, role="owner")
        self.member = baker.make(
            "app.Membership", tenant=self.tenant, role="member", user__email="mia@acme.example"
        )
        _login(self.client, self.owner.user, self.tenant)

    def _toast(self, response):
        return json.loads(response["HX-Trigger"])["toast"]

    def test_role_change_redraws_the_panel(self):
        response = self.client.post(
            reverse("change_member_role", args=[self.member.pk]), {"role": "admin"}, **self.HTMX
        )

        assert response.status_code == 200
        html = response.content.decode()
        assert 'id="members-panel"' in html
        assert "<html" not in html
        assert self._toast(response) == {"level": "success", "text": "mia@acme.example is now admin."}

    def test_a_refusal_toasts_the_reason(self):
        response = self.client.post(
            reverse("change_member_role", args=[self.owner.pk]), {"role": "member"}, **self.HTMX
        )

        assert self._toast(response)["level"] == "error"
        assert "without an owner" in self._toast(response)["text"]

    def test_changing_your_own_role_reloads_the_page(self):
        baker.make("app.Membership", tenant=self.tenant, role="owner")

        response = self.client.post(
            reverse("change_member_role", args=[self.owner.pk]), {"role": "admin"}, **self.HTMX
        )

        assert response["HX-Refresh"] == "true"

    def test_remove(self):
        response = self.client.post(reverse("remove_member", args=[self.member.pk]), **self.HTMX)

        assert "mia@acme.example" not in response.content.decode()
        assert self._toast(response)["text"] == "mia@acme.example removed."

    def test_invite_keeps_what_was_typed_when_it_fails(self):
        response = self.client.post(
            reverse("invite_member"), {"email": "ghost@acme.example", "role": "admin"}, **self.HTMX
        )

        assert self._toast(response)["level"] == "error"
        assert 'value="ghost@acme.example"' in response.content.decode()

    def test_invite(self):
        baker.make("app.User", email="new@acme.example")

        response = self.client.post(
            reverse("invite_member"), {"email": "new@acme.example", "role": "member"}, **self.HTMX
        )

        assert "new@acme.example" in response.content.decode()
        assert self._toast(response)["text"] == "new@acme.example added as member."

    def test_leaving_navigates_away(self):
        _login(self.client, self.member.user, self.tenant)

        response = self.client.post(reverse("leave_workspace"), **self.HTMX)

        assert response["HX-Redirect"] == reverse("dashboard")

    def test_actions_ask_for_confirmation(self):
        html = self.client.get(reverse("tenant_settings")).content.decode()

        assert 'hx-confirm="role"' in html
        assert 'hx-confirm="Remove mia@acme.example?"' in html
        assert 'id="confirm-dialog"' in html
