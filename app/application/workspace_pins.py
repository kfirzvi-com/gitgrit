"""Pinning workspaces to the top of the navbar workspace picker."""
from django.db import IntegrityError, transaction

from app.domain.models import Membership, Tenant, WorkspacePin
from app.domain.workspace_picker import PinEligibility


class PinNotAllowed(Exception):
    """The workspace doesn't exist, or the user can't open it."""


def toggle_pin(user, tenant_id) -> bool:
    """Pin ``tenant_id`` for ``user``, or unpin it if already pinned.
    Returns whether it is pinned now."""
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        raise PinNotAllowed
    is_member = Membership.objects.filter(user=user, tenant=tenant).exists()
    if not PinEligibility.allows(is_member=is_member, is_superuser=user.is_superuser):
        raise PinNotAllowed

    deleted, _ = WorkspacePin.objects.filter(user=user, tenant=tenant).delete()
    if deleted:
        return False
    try:
        with transaction.atomic():
            WorkspacePin.objects.create(user=user, tenant=tenant)
    except IntegrityError:
        pass  # a concurrent toggle pinned it already
    return True
