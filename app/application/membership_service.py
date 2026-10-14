"""Who is in a workspace, and as what.

Invariant: every workspace has at least one owner, so it is never without
members either. A workspace is born with its owner (``create_workspace``)
and loses its last owner only by being deleted. Everything that removes a
member or changes a role goes through here, which checks it under a lock on
the workspace row; ``guard_last_owner`` backs that up for writes made around
this module (the Django admin, deleting a user).

Who may do what:
- owners and admins manage admins and members;
- only owners (and superusers) make someone an owner, or touch an owner.
"""
from django.db import transaction
from django.db.models import QuerySet

from app.application.event_bus import publish
from app.domain.events import MemberRemoved, MemberRoleChanged
from app.domain.models import Membership, Tenant

OWNER = Membership.Role.OWNER


class LastOwnerError(ValueError):
    """The change would leave a workspace without an owner."""

    def __init__(self, tenant_name: str = ""):
        where = f'"{tenant_name}"' if tenant_name else "the workspace"
        super().__init__(
            f"That would leave {where} without an owner. Make someone else an owner first."
        )


class NotAllowed(PermissionError):
    pass


def _actor_role(actor, tenant: Tenant) -> str | None:
    if actor.is_superuser:
        return OWNER
    return (
        Membership.objects.filter(user=actor, tenant=tenant)
        .values_list("role", flat=True)
        .first()
    )


def can_manage_members(actor, tenant: Tenant) -> bool:
    return _actor_role(actor, tenant) in (OWNER, Membership.Role.ADMIN)


def can_manage_owners(actor, tenant: Tenant) -> bool:
    return _actor_role(actor, tenant) == OWNER


def _other_owner_exists(membership: Membership) -> bool:
    return (
        Membership.objects.filter(tenant_id=membership.tenant_id, role=OWNER)
        .exclude(pk=membership.pk)
        .exists()
    )


def _lock(tenant_id) -> Tenant:
    """Serialise ownership changes per workspace, so two owners demoting each
    other at once can't both see the other as the remaining owner."""
    return Tenant.objects.select_for_update().get(pk=tenant_id)


def change_role(membership: Membership, new_role: str, actor) -> Membership:
    if new_role not in Membership.Role.values:
        raise ValueError(f"Unknown role {new_role!r}.")
    with transaction.atomic():
        tenant = _lock(membership.tenant_id)
        membership.refresh_from_db()
        old_role = membership.role
        if old_role == new_role:
            return membership
        if not can_manage_members(actor, tenant):
            raise NotAllowed("Only owners and admins change roles.")
        if OWNER in (old_role, new_role) and not can_manage_owners(actor, tenant):
            raise NotAllowed("Only owners make or unmake owners.")
        if old_role == OWNER and not _other_owner_exists(membership):
            raise LastOwnerError(tenant.name)
        membership.role = new_role
        membership.save(update_fields=["role"])
    publish(
        MemberRoleChanged(
            tenant_id=str(tenant.pk),
            user_id=str(membership.user_id),
            old_role=old_role,
            new_role=new_role,
            changed_by_user_id=str(actor.pk),
        )
    )
    return membership


def remove_member(membership: Membership, actor) -> None:
    """``actor`` removes someone else, or themselves (leaving)."""
    leaving = membership.user_id == actor.pk
    with transaction.atomic():
        tenant = _lock(membership.tenant_id)
        membership.refresh_from_db()
        if not leaving:
            if not can_manage_members(actor, tenant):
                raise NotAllowed("Only owners and admins remove members.")
            if membership.role == OWNER and not can_manage_owners(actor, tenant):
                raise NotAllowed("Only owners remove owners.")
        if membership.role == OWNER and not _other_owner_exists(membership):
            raise LastOwnerError(tenant.name)
        membership.delete()
    publish(
        MemberRemoved(
            tenant_id=str(tenant.pk),
            user_id=str(membership.user_id),
            removed_by_user_id=str(actor.pk),
        )
    )


def is_last_owner(membership: Membership) -> bool:
    return membership.role == OWNER and not _other_owner_exists(membership)


# --- Backstop for writes that don't come through this module -------------


def _deleting_model(origin):
    if isinstance(origin, QuerySet):
        return origin.model
    return type(origin)


def guard_last_owner_delete(sender, instance, origin=None, **kwargs):
    """pre_delete: deleting the workspace takes its memberships with it, which
    is fine. Anything else (a user being deleted, a membership removed in the
    admin) must leave an owner behind."""
    if _deleting_model(origin) is Tenant:
        return
    if is_last_owner(instance):
        raise LastOwnerError(instance.tenant.name)


def guard_last_owner_save(sender, instance, raw=False, update_fields=None, **kwargs):
    """pre_save: demoting the last owner."""
    if raw or instance._state.adding or instance.role == OWNER:
        return
    if update_fields is not None and "role" not in update_fields:
        return
    old_role = (
        Membership.objects.filter(pk=instance.pk).values_list("role", flat=True).first()
    )
    if old_role == OWNER and not _other_owner_exists(instance):
        raise LastOwnerError(instance.tenant.name)
