"""Inviting someone into a workspace, end to end: the invitation email's
link, signing up or in through it, accepting, and the banner."""
import json
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import AccessRequest, Membership, User, WorkspaceInvitation

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.mark.django_db
@override_settings(SIGNUP_MODE="onboarding")
class TestInvitationFlows(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = baker.make("app.Tenant", name="Acme")
        self.owner = baker.make(
            "app.Membership", tenant=self.tenant, role="owner",
            user__email="olga@acme.example", user__first_name="Olga", user__last_name="Owner",
        ).user

    def _invite(self, email="new@acme.example", role="admin"):
        self.client.force_login(self.owner)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.pk)
        session.save()
        with mock.patch("app.tasks.send_email.defer") as defer, self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("invite_member"), {"email": email, "role": role}, **HTMX)
        self.client.logout()
        return defer.call_args.kwargs["context"]["accept_path"]

    def test_someone_new_signs_up_through_the_invitation(self):
        link = self._invite()

        page = self.client.get(link).content.decode()
        assert "Join Acme on GitGrit" in page
        assert "Olga Owner" in page and "as <strong>admin</strong>" in page
        assert "Create your GitGrit account" in page
        assert 'value="new@acme.example"' in page

        response = self.client.post(
            reverse("account_login"), {"login": "new@acme.example", "password": "a-long-passphrase"}
        )

        assert response.headers["Location"] == reverse("dashboard")
        user = User.objects.get(email="new@acme.example")
        assert user.is_active and self.client.session["_auth_user_id"] == str(user.pk)
        assert Membership.objects.get(user=user).tenant == self.tenant
        assert self.client.session["active_tenant_id"] == str(self.tenant.pk)
        # Invited, so no access request and no confirmation email.
        assert not AccessRequest.objects.filter(user=user).exists()
        assert EmailAddress.objects.get(user=user).verified

    def test_signing_up_with_another_address_is_an_ordinary_access_request(self):
        link = self._invite()
        self.client.get(link)
        with mock.patch("app.tasks.send_email.defer"):
            self.client.post(
                reverse("account_login"), {"login": "other@acme.example", "password": "a-long-passphrase"}
            )
        other = User.objects.get(email="other@acme.example")
        assert not other.is_active and AccessRequest.objects.filter(user=other).exists()
        assert not Membership.objects.filter(user=other).exists()

    def test_someone_with_an_account_signs_in_and_accepts(self):
        user = baker.make("app.User", email="new@acme.example")
        user.set_password("a-long-passphrase")
        user.save()
        link = self._invite()

        page = self.client.get(link).content.decode()
        assert "Sign in as new@acme.example to accept." in page
        assert f'name="next" value="{link}"' in page

        response = self.client.post(
            reverse("account_login"),
            {"login": "new@acme.example", "password": "a-long-passphrase", "next": link},
        )
        assert response.headers["Location"] == link
        assert "Accept and join" in self.client.get(link).content.decode()
        assert not Membership.objects.filter(user=user).exists()

        token = link.rstrip("/").rsplit("/", 1)[-1]
        response = self.client.post(reverse("accept_invitation", args=[token]))

        assert response.headers["Location"] == reverse("dashboard")
        assert Membership.objects.get(user=user).role == "admin"

    def test_signed_in_as_someone_else(self):
        link = self._invite()
        self.client.force_login(baker.make("app.User", email="eve@evil.example"))

        page = self.client.get(link).content.decode()

        assert "but this invitation is for new@acme.example" in page
        assert "Accept and join" not in page

    def test_withdrawn_links_stop_working(self):
        link = self._invite()
        invitation = WorkspaceInvitation.objects.get(email="new@acme.example")
        invitation.revoke()
        invitation.save()

        response = self.client.get(link)

        assert response.status_code == 404
        assert b"This invitation isn't valid" in response.content

    def test_waiting_for_approval_but_invited_gets_in(self):
        pending = baker.make("app.User", email="new@acme.example", is_active=False)
        pending.set_password("a-long-passphrase")
        pending.save()
        AccessRequest.objects.create(user=pending)
        link = self._invite()
        self.client.get(link)

        response = self.client.post(
            reverse("account_login"), {"login": "new@acme.example", "password": "a-long-passphrase"}
        )

        assert response.headers["Location"] == reverse("dashboard")
        pending.refresh_from_db()
        assert pending.is_active
        assert Membership.objects.get(user=pending).tenant == self.tenant

    def test_banner_for_a_signed_in_invitee(self):
        user = baker.make("app.User", email="new@acme.example")
        EmailAddress.objects.create(user=user, email="new@acme.example", verified=True, primary=True)
        self._invite()
        self.client.force_login(user)

        page = self.client.get(reverse("no_workspace")).content.decode()
        assert "invited you to join <strong>Acme</strong> as admin" in page

        invitation = WorkspaceInvitation.objects.get(email="new@acme.example")
        response = self.client.post(reverse("decline_invitation_in_app", args=[invitation.pk]), **HTMX)
        assert json.loads(response["HX-Trigger"])["toast"]["text"] == "You declined the invitation to Acme."
        assert "invited you to join" not in self.client.get(reverse("no_workspace")).content.decode()

    def test_pending_invitations_in_the_member_list(self):
        self._invite()
        self.client.force_login(self.owner)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.pk)
        session.save()

        html = self.client.get(reverse("tenant_settings")).content.decode()

        assert 'data-invitation="new@acme.example"' in html
        invitation = WorkspaceInvitation.objects.get(email="new@acme.example")
        assert reverse("revoke_invitation", args=[invitation.pk]) in html


@pytest.mark.django_db
@override_settings(SIGNUP_MODE="onboarding")
class TestProviderSignupFromInvitation(TestCase):
    """Continue with Google/GitHub/GitLab from the invitation page."""

    def test_the_invited_address_is_let_in_and_joins(self):
        from types import SimpleNamespace

        from django.test import RequestFactory

        from app.application import invitations
        from app.presentation.auth_adapters import INVITATION_SESSION_KEY, SocialAccountAdapter

        tenant = baker.make("app.Tenant", name="Acme")
        owner = baker.make("app.Membership", tenant=tenant, role="owner").user
        with mock.patch("app.tasks.send_email.defer") as defer, self.captureOnCommitCallbacks(execute=True):
            invitations.invite(tenant, "new@acme.example", "member", owner)
        token = defer.call_args.kwargs["context"]["accept_path"].rstrip("/").rsplit("/", 1)[-1]

        request = RequestFactory().get("/")
        request.session = {INVITATION_SESSION_KEY: token}
        adapter = SocialAccountAdapter()
        user = adapter.new_user(request, None)
        user.email, user.username = "new@acme.example", "new"
        adapter.save_user(request, SimpleNamespace(user=user, save=lambda request: user.save()))

        user.refresh_from_db()
        assert user.is_active
        assert not AccessRequest.objects.filter(user=user).exists()
        assert Membership.objects.get(user=user).tenant == tenant
        assert request.session["active_tenant_id"] == str(tenant.pk)


@pytest.mark.django_db
class TestInviteForm(TestCase):
    def test_role_defaults_to_member(self):
        tenant = baker.make("app.Tenant")
        owner = baker.make("app.Membership", tenant=tenant, role="owner").user
        self.client.force_login(owner)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.pk)
        session.save()

        html = self.client.get(reverse("tenant_settings")).content.decode()

        assert '<option value="member" selected>' in html
        assert '<option value="owner" selected>' not in html


@pytest.mark.django_db
class TestInvitationPageWording(TestCase):
    def test_no_access_request_hint_on_an_invitation(self):
        from app.application import invitations

        tenant = baker.make("app.Tenant")
        owner = baker.make("app.Membership", tenant=tenant, role="owner").user
        with mock.patch("app.tasks.send_email.defer") as defer, self.captureOnCommitCallbacks(execute=True):
            invitations.invite(tenant, "new@acme.example", "member", owner)

        html = self.client.get(defer.call_args.kwargs["context"]["accept_path"]).content.decode()

        assert "asks us for access" not in html
