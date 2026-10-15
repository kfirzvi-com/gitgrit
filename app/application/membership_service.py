"""Changing who is in a workspace: load the roster, let the domain decide
(``app.domain.workspace_roles``), store the outcome and publish its event.

Each change holds a lock on the workspace row, so two owners demoting each
other at the same moment can't both see the other as the remaining owner.
"""
from django.db import transaction

from app.application.event_bus import publish
from app.domain.models import Membership, Tenant
from app.domain.workspace_roles import Roster, Seat


def roster_of(tenant: Tenant, memberships=None) -> Roster:
    memberships = (
        memberships
        if memberships is not None
        else Membership.objects.filter(tenant=tenant)
    )
    return Roster(
        tenant.pk,
        [Seat(str(m.user_id), m.role) for m in memberships],
        tenant.name,
    )


def actor_in(roster: Roster, user):
    return roster.actor(user.pk, is_superuser=user.is_superuser)


def _locked_roster(tenant_id):
    tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
    rows = {str(m.user_id): m for m in Membership.objects.filter(tenant=tenant)}
    return tenant, roster_of(tenant, rows.values()), rows


def add_member(tenant: Tenant, user, role: str, by) -> Membership:
    with transaction.atomic():
        tenant, roster, _ = _locked_roster(tenant.pk)
        event = roster.add(actor_in(roster, by), user.pk, role)
        membership = Membership.objects.create(
            user=user, tenant=tenant, role=role, granted_by=by
        )
    publish(event)
    return membership


def change_role(membership: Membership, new_role: str, by) -> Membership:
    with transaction.atomic():
        tenant, roster, rows = _locked_roster(membership.tenant_id)
        event = roster.change_role(actor_in(roster, by), membership.user_id, new_role)
        membership = rows[str(membership.user_id)]
        if event is None:
            return membership
        membership.grant(new_role, by)
        membership.save(update_fields=["role", "granted_by", "granted_at"])
    publish(event)
    return membership


def remove_member(membership: Membership, by) -> None:
    """``by`` removes someone else, or themselves (leaving)."""
    with transaction.atomic():
        _, roster, rows = _locked_roster(membership.tenant_id)
        event = roster.remove(actor_in(roster, by), membership.user_id)
        rows[str(membership.user_id)].delete()
    publish(event)
