"""Creating and deleting workspaces (``Tenant`` in code).

Workspaces are gated: only superusers create them (directly, or while
approving an access request), and nobody gets one of their own on signup.
Deleting one is for its owners and superusers, and is permanent.
"""
import logging

from django.db import transaction
from django.utils.text import slugify

from app.application.event_bus import publish
from app.application.membership_service import actor_in, roster_of
from app.domain import workspace_roles
from app.domain.models import Membership, Project, Tenant
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger("app.access")


def create_workspace(name: str, owner, *, by=None, role: str = workspace_roles.OWNER) -> Tenant:
    """A new workspace with a unique slug derived from ``name``, founded by
    ``owner`` (the domain insists the founder is its owner). ``by`` is who
    set it up, when that's someone else; ``owner`` hears about it then."""
    base_slug = slugify(name) or "workspace"
    slug = base_slug
    counter = 1
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    with transaction.atomic():
        tenant = Tenant.objects.create(name=name, slug=slug)
        _, joined = workspace_roles.found(
            tenant.pk, owner.pk, role=role, by_user_id=by.pk if by else None,
            workspace_name=name,
        )
        Membership.objects.create(user=owner, tenant=tenant, role=joined.role)
    if by is not None and by != owner:
        publish(joined)
    return tenant


def can_delete_workspace(user, tenant: Tenant) -> bool:
    roster = roster_of(tenant)
    return roster.can_delete_workspace(actor_in(roster, user))


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
