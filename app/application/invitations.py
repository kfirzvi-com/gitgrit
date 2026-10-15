"""Inviting people into a workspace, and their accepting.

The rules live in the domain: ``Roster.check_invite`` (who may invite whom),
``WorkspaceInvitation`` (an open invitation, for one address, for a while)
and ``Roster.admit`` (joining). This module loads, locks, stores, emails and
publishes.

An invitation is how anyone joins a workspace someone else runs. It also lets
a person into GitGrit itself: the inviting owner or admin vouches for them,
so there is no access request to approve, and following the emailed link
proves the address is theirs.
"""
import logging

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from app.application.event_bus import publish
from app.application.membership_service import actor_in, roster_of
from app.application.outbox import send_later
from app.domain.models import (
    AccessRequest,
    InvitationError,
    Membership,
    Tenant,
    WorkspaceInvitation,
)
from app.domain.workspace_roles import ROLE_LABELS, AlreadyMember, NotAllowed

logger = logging.getLogger("app.access")

User = get_user_model()


# --- sending ----------------------------------------------------------------


def invite(tenant: Tenant, email: str, role: str, by) -> WorkspaceInvitation:
    """Invite ``email`` into ``tenant`` as ``role``, or send a pending
    invitation for it again (with a fresh link and ``role``)."""
    email = WorkspaceInvitation.normalise(email)
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
        roster = roster_of(tenant)
        roster.check_invite(actor_in(roster, by), role)
        existing = User.objects.filter(email__iexact=email).first()
        if existing is not None and roster.seat_of(existing.pk) is not None:
            raise AlreadyMember()
        invitation = tenant.invitations.filter(
            email=email, status=WorkspaceInvitation.Status.PENDING
        ).first()
        if invitation is None:
            invitation, token = WorkspaceInvitation.issue(tenant, email, role, by)
        else:
            token = invitation.renew(role=role, invited_by=by)
        invitation.save()
        _email_invitation(invitation, token, has_account=existing is not None)
    logger.info("invitation for %s to %s as %s sent by %s", email, tenant.slug, role, by.pk)
    return invitation


def resend(invitation: WorkspaceInvitation, by) -> WorkspaceInvitation:
    _check_can_manage(invitation, by)
    return invite(invitation.tenant, invitation.email, invitation.role, by)


def revoke(invitation: WorkspaceInvitation, by) -> None:
    _check_can_manage(invitation, by)
    invitation.revoke()
    invitation.save(update_fields=["status", "closed_at"])
    logger.info("invitation %s for %s revoked by %s", invitation.pk, invitation.email, by.pk)


def pending_for_workspace(tenant: Tenant):
    return tenant.invitations.filter(status=WorkspaceInvitation.Status.PENDING).select_related(
        "invited_by"
    )


def _check_can_manage(invitation, by):
    roster = roster_of(invitation.tenant)
    if not roster.can_manage_invitation(actor_in(roster, by), invitation.role):
        raise NotAllowed("Only owners and admins manage invitations; only owners, owner ones.")


def _email_invitation(invitation, token, *, has_account):
    inviter = invitation.invited_by
    send_later(
        "workspace_invitation",
        [invitation.email],
        {
            "workspace": invitation.tenant.name,
            "role": ROLE_LABELS[invitation.role].lower(),
            "inviter_name": (inviter.get_full_name() if inviter else "") or "",
            "inviter_email": inviter.email if inviter else "",
            "accept_path": reverse("invitation", args=[token]),
            "has_account": has_account,
            "expires": invitation.expires_at.strftime("%-d %B %Y"),
        },
    )


# --- the invitee ------------------------------------------------------------


def find_open(token: str) -> WorkspaceInvitation | None:
    if not token:
        return None
    invitation = (
        WorkspaceInvitation.objects.select_related("tenant", "invited_by")
        .filter(token_hash=WorkspaceInvitation.hash_token(token))
        .first()
    )
    return invitation if invitation is not None and invitation.is_open() else None


def emails_of(user, *, via_link: bool) -> list[str]:
    """The addresses an invitation may be for, for ``user`` to take it.

    Their confirmed addresses, always. Following the emailed link also proves
    the address it went to, so then their account email counts too, confirmed
    or not. Without the link (from inside the app) it has to be confirmed:
    anyone can type an address at sign-up."""
    verified = list(
        EmailAddress.objects.filter(user=user, verified=True).values_list("email", flat=True)
    )
    return [user.email, *verified] if via_link and user.email else verified


def open_for(user):
    """Invitations waiting for ``user``, to show them in the app."""
    if not user.is_authenticated:
        return WorkspaceInvitation.objects.none()
    addresses = {WorkspaceInvitation.normalise(e) for e in emails_of(user, via_link=False)}
    return WorkspaceInvitation.objects.select_related("tenant", "invited_by").filter(
        email__in=addresses,
        status=WorkspaceInvitation.Status.PENDING,
        expires_at__gt=timezone.now(),
    )


def accept(invitation: WorkspaceInvitation, user, *, via_link: bool) -> Membership:
    """``user`` accepts: they join the workspace as invited. Someone still
    waiting on an access request is let in: the inviter vouches for them,
    and the link proved their address."""
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(pk=invitation.tenant_id)
        invitation = WorkspaceInvitation.objects.select_for_update().get(pk=invitation.pk)
        invitation.accept(user, emails_of(user, via_link=via_link))
        roster = roster_of(tenant)
        try:
            joined = roster.admit(user.pk, invitation.role, invitation.invited_by_id)
        except AlreadyMember:
            raise InvitationError(f"You're already in {tenant.name}.")
        membership = Membership.objects.create(
            user=user, tenant=tenant, role=invitation.role, granted_by=invitation.invited_by
        )
        invitation.save(update_fields=["status", "closed_at", "accepted_by"])
        _let_in(user, invitation)
    publish(joined)
    logger.info("invitation %s accepted by %s into %s", invitation.pk, user.pk, tenant.slug)
    return membership


def decline(invitation: WorkspaceInvitation, user, *, via_link: bool) -> None:
    invitation.decline(emails_of(user, via_link=via_link))
    invitation.save(update_fields=["status", "closed_at"])
    logger.info("invitation %s declined by %s", invitation.pk, user.pk)


def sign_up_and_accept(invitation: WorkspaceInvitation, email: str, password: str):
    """Someone new, from the invitation link, with an email and password:
    an active account (no access request: they were invited), its address
    confirmed by the link, and in the workspace."""
    from allauth.account.adapter import get_adapter

    if not invitation.is_for([email]):
        raise InvitationError(
            f"This invitation is for {invitation.email}. Sign up with that address."
        )
    with transaction.atomic():
        user = User(email=invitation.email, is_active=True)
        get_adapter().populate_username(None, user)
        user.set_password(password)
        user.save()
        EmailAddress.objects.create(user=user, email=invitation.email, primary=True, verified=True)
        accept(invitation, user, via_link=True)
    return user


def _let_in(user, invitation):
    if user.is_active:
        return
    access_request = AccessRequest.objects.filter(
        user=user, status=AccessRequest.Status.PENDING
    ).first()
    if access_request is not None:
        access_request.confirm_email()
        access_request.approve(invitation.invited_by)
        access_request.save(update_fields=["status", "reviewed_by", "reviewed_at", "email_confirmed_at"])
    user.is_active = True
    user.save(update_fields=["is_active"])
    EmailAddress.objects.filter(user=user, email__iexact=invitation.email).update(verified=True)
