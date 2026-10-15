"""An invitation: good for one address, for a while, once."""
from datetime import timedelta
from unittest import TestCase

from django.utils import timezone

from app.domain.models import InvitationError, Tenant, User, WorkspaceInvitation
from app.domain.workspace_roles import (
    ADMIN,
    MEMBER,
    OWNER,
    AlreadyMember,
    NotAllowed,
    Roster,
    Seat,
)


def _invite(email="Ada@Example.com", role=MEMBER):
    return WorkspaceInvitation.issue(Tenant(name="Acme"), email, role, User(email="olga@example.com"))


class InvitationTests(TestCase):
    def test_issued_for_one_normalised_address_with_a_secret_link(self):
        invitation, token = _invite()

        self.assertEqual(invitation.email, "ada@example.com")
        self.assertEqual(invitation.token_hash, WorkspaceInvitation.hash_token(token))
        self.assertNotIn(token, invitation.token_hash)
        self.assertTrue(invitation.is_open())

    def test_open_for_its_lifetime_only(self):
        invitation, _ = _invite()
        later = timezone.now() + WorkspaceInvitation.LIFETIME + timedelta(minutes=1)
        self.assertFalse(invitation.is_open(now=later))

    def test_renewing_replaces_the_link_and_the_clock(self):
        invitation, first = _invite()
        invitation.expires_at = timezone.now()

        second = invitation.renew(role=ADMIN)

        self.assertNotEqual(first, second)
        self.assertEqual(invitation.token_hash, WorkspaceInvitation.hash_token(second))
        self.assertEqual(invitation.role, ADMIN)
        self.assertTrue(invitation.is_open())

    def test_accepted_by_the_invited_address_only(self):
        invitation, _ = _invite()
        with self.assertRaises(InvitationError):
            invitation.accept(User(), ["someone@else.com"])

        invitation.accept(User(), ["ADA@example.com"])

        self.assertEqual(invitation.status, WorkspaceInvitation.Status.ACCEPTED)

    def test_used_once(self):
        invitation, _ = _invite()
        invitation.accept(User(), ["ada@example.com"])
        for act in (lambda: invitation.accept(User(), ["ada@example.com"]), invitation.revoke):
            with self.assertRaises(InvitationError):
                act()

    def test_an_expired_invitation_cant_be_accepted(self):
        invitation, _ = _invite()
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        with self.assertRaises(InvitationError):
            invitation.accept(User(), ["ada@example.com"])

    def test_declined_or_revoked_is_closed(self):
        declined, _ = _invite()
        declined.decline(["ada@example.com"])
        revoked, _ = _invite()
        revoked.revoke()
        for invitation in (declined, revoked):
            self.assertFalse(invitation.is_open())


class WhoInvitesTests(TestCase):
    def setUp(self):
        self.roster = Roster("ws", [Seat("olga", OWNER), Seat("adam", ADMIN), Seat("mia", MEMBER)])

    def test_owners_and_admins_invite_only_owners_invite_owners(self):
        self.roster.check_invite(self.roster.actor("olga"), OWNER)
        self.roster.check_invite(self.roster.actor("adam"), ADMIN)
        with self.assertRaises(NotAllowed):
            self.roster.check_invite(self.roster.actor("adam"), OWNER)
        with self.assertRaises(NotAllowed):
            self.roster.check_invite(self.roster.actor("mia"), MEMBER)

    def test_managing_an_invitation_follows_who_could_send_it(self):
        self.assertTrue(self.roster.can_manage_invitation(self.roster.actor("adam"), MEMBER))
        self.assertFalse(self.roster.can_manage_invitation(self.roster.actor("adam"), OWNER))

    def test_accepting_admits_with_the_inviter_on_record(self):
        joined = self.roster.admit("new", ADMIN, invited_by_user_id="adam")
        self.assertEqual(self.roster.seat_of("new"), Seat("new", ADMIN))
        self.assertEqual(joined.added_by_user_id, "adam")
        with self.assertRaises(AlreadyMember):
            self.roster.admit("mia", MEMBER)
