"""The invitation service: sending, managing and accepting, with storage,
email and events."""
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.test import TestCase
from model_bakery import baker

from app.application import invitations
from app.domain.models import AccessRequest, InvitationError, Membership, WorkspaceInvitation
from app.domain.workspace_roles import AlreadyMember, NotAllowed


@pytest.mark.django_db
class TestInvitations(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant", name="Acme")
        self.owner = baker.make("app.Membership", tenant=self.tenant, role="owner",
                                user__email="olga@acme.example", user__first_name="Olga")
        self.admin = baker.make("app.Membership", tenant=self.tenant, role="admin")
        self.member = baker.make("app.Membership", tenant=self.tenant, role="member")

    def _invite(self, email="new@acme.example", role="member", by=None):
        with mock.patch("app.tasks.send_email.defer") as defer, self.captureOnCommitCallbacks(execute=True):
            invitation = invitations.invite(self.tenant, email, role, by or self.owner.user)
        return invitation, defer

    def _token(self, defer):
        return defer.call_args.kwargs["context"]["accept_path"].rstrip("/").rsplit("/", 1)[-1]

    def test_invite_emails_the_link_and_adds_nobody(self):
        invitation, defer = self._invite()

        kwargs = defer.call_args.kwargs
        assert (kwargs["template"], kwargs["to"]) == ("workspace_invitation", ["new@acme.example"])
        assert kwargs["context"]["inviter_name"] == "Olga"
        assert kwargs["context"]["has_account"] is False
        assert invitations.find_open(self._token(defer)) == invitation
        assert Membership.objects.filter(tenant=self.tenant).count() == 3

    def test_who_may_invite(self):
        with pytest.raises(NotAllowed):
            self._invite(by=self.member.user)
        with pytest.raises(NotAllowed):
            self._invite(role="owner", by=self.admin.user)
        with pytest.raises(AlreadyMember):
            self._invite(email=self.member.user.email)

    def test_inviting_again_resends_with_a_fresh_link(self):
        first, defer1 = self._invite()
        second, defer2 = self._invite(role="admin")

        assert first.pk == second.pk and second.role == "admin"
        assert invitations.find_open(self._token(defer1)) is None
        assert invitations.find_open(self._token(defer2)) == second

    def test_revoke_and_resend_are_for_those_who_could_send_it(self):
        invitation, _ = self._invite(role="owner")
        with pytest.raises(NotAllowed):
            invitations.revoke(invitation, self.admin.user)
        invitations.revoke(invitation, self.owner.user)
        assert not invitation.is_open()

    def test_accepting_through_the_link_joins_with_the_inviter_on_record(self):
        invitation, _ = self._invite()
        user = baker.make("app.User", email="new@acme.example")

        with mock.patch("app.application.invitations.publish") as publish:
            membership = invitations.accept(invitation, user, via_link=True)

        assert (membership.role, membership.granted_by) == ("member", self.owner.user)
        assert publish.call_args.args[0].added_by_user_id == str(self.owner.user.pk)
        invitation.refresh_from_db()
        assert invitation.status == "accepted" and invitation.accepted_by == user

    def test_without_the_link_the_address_must_be_confirmed(self):
        invitation, _ = self._invite()
        user = baker.make("app.User", email="new@acme.example")
        assert list(invitations.open_for(user)) == []
        with pytest.raises(InvitationError):
            invitations.accept(invitation, user, via_link=False)

        EmailAddress.objects.create(user=user, email="new@acme.example", verified=True, primary=True)
        assert list(invitations.open_for(user)) == [invitation]
        invitations.accept(invitation, user, via_link=False)

    def test_someone_else_cant_take_it(self):
        invitation, _ = self._invite()
        with pytest.raises(InvitationError):
            invitations.accept(invitation, baker.make("app.User", email="eve@evil.example"), via_link=True)

    def test_someone_waiting_for_access_is_let_in(self):
        invitation, _ = self._invite()
        user = baker.make("app.User", email="new@acme.example", is_active=False)
        request = AccessRequest.objects.create(user=user)

        invitations.accept(invitation, user, via_link=True)

        user.refresh_from_db()
        request.refresh_from_db()
        assert user.is_active
        assert request.status == "approved" and request.reviewed_by == self.owner.user

    def test_signing_up_from_the_invitation(self):
        invitation, _ = self._invite()

        user = invitations.sign_up_and_accept(invitation, "NEW@acme.example", "a-long-passphrase")

        assert user.is_active and user.check_password("a-long-passphrase")
        assert EmailAddress.objects.get(user=user).verified
        assert not AccessRequest.objects.filter(user=user).exists()
        assert Membership.objects.get(user=user).tenant == self.tenant

    def test_one_pending_invitation_per_address(self):
        self._invite()
        self._invite()
        assert WorkspaceInvitation.objects.filter(email="new@acme.example").count() == 1
