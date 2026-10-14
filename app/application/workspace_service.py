"""Creating and deleting workspaces (``Tenant`` in code).

Workspaces are gated: only superusers create them (directly, or while
approving an access request), and nobody gets one of their own on signup.
Deleting one is for its owners and superusers, and is permanent.
"""
import logging

from django.db import transaction
from django.utils.text import slugify

from app.domain.models import Membership, Project, Tenant
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger("app.access")


def create_workspace(name: str, owner) -> Tenant:
    """A new workspace with a unique slug derived from ``name``, owned by
    ``owner``. A workspace always has an owner, from birth."""
    base_slug = slugify(name) or "workspace"
    slug = base_slug
    counter = 1
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    with transaction.atomic():
        tenant = Tenant.objects.create(name=name, slug=slug)
        Membership.objects.create(user=owner, tenant=tenant, role=Membership.Role.OWNER)
    return tenant


def can_delete_workspace(user, tenant: Tenant) -> bool:
    """Owners, through a real membership, and superusers."""
    if user.is_superuser:
        return True
    return tenant.memberships.filter(user=user, role="owner").exists()


def delete_workspace(tenant: Tenant, actor) -> None:
    """Delete ``tenant`` and everything in it. Irreversible.

    The database cascade removes the workspace's rows. What lives outside it
    is cleaned up first, best effort: each project's webhook on GitHub/GitLab,
    so the platform stops posting to a workspace that is gone. A webhook that
    can't be removed (revoked token, repo already deleted) is logged and
    skipped — it would only ever get 404s from us.
    """
    projects = (
        Project.objects.filter(tenant=tenant)
        .exclude(webhook_id="")
        .select_related("platform_connection")
    )
    for project in projects:
        try:
            client = get_platform_client(project.platform_connection)
            client.delete_webhook(project.external_id, project.webhook_id)
        except Exception:
            logger.exception(
                "workspace delete: could not remove webhook for project %s", project.pk
            )

    tenant_id, slug = tenant.pk, tenant.slug
    with transaction.atomic():
        tenant.delete()
    logger.warning(
        "workspace %s (%s) deleted by %s (%s)",
        slug,
        tenant_id,
        actor.pk,
        actor.email or actor.username,
    )
