"""Who may act in the current workspace, and the superuser "support view".

Workspaces (``Tenant`` in code) are normally reached only through a
``Membership`` row. A Django superuser may additionally switch into any
workspace to help a customer. That state is the *support view*: it lives in
the session until the superuser switches back, logs in again or logs out,
and grants the same access a workspace owner has. Every entry and every write
made while it is on is logged at warning level so "what did you change?" can
be answered.
"""
import logging
import uuid

from django.utils import timezone

from app.domain.models import Membership, Tenant

logger = logging.getLogger("app.support_view")

# Session keys. ``active_tenant_id`` is the workspace the user is in; the
# support marker (the entry time) is present only while a superuser is in a
# workspace they are not a member of, and is what makes the middleware trust
# that id. A bare foreign id without the marker is never honoured.
ACTIVE_TENANT_KEY = "active_tenant_id"
SUPPORT_VIEW_STARTED_KEY = "support_view_started_at"

ADMIN_ROLES = (Membership.Role.OWNER, Membership.Role.ADMIN)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def parse_tenant_id(value):
    """Return ``value`` as a UUID, or None when it is missing or malformed."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def is_workspace_admin(request) -> bool:
    """True when the request user may manage the active workspace.

    Owners and admins qualify through their membership; a superuser qualifies
    in every workspace, which is what makes the support view useful.
    """
    tenant = getattr(request, "tenant", None)
    user = getattr(request, "user", None)
    if tenant is None or user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return Membership.objects.filter(
        user=user, tenant=tenant, role__in=ADMIN_ROLES
    ).exists()


def has_admin_membership(request) -> bool:
    """True only for a real OWNER/ADMIN membership; superuser status does not
    count. Used where the support view must stay out, e.g. revealing a stored
    access token."""
    tenant = getattr(request, "tenant", None)
    if tenant is None:
        return False
    return Membership.objects.filter(
        user=request.user, tenant=tenant, role__in=ADMIN_ROLES
    ).exists()


def enter_support_view(request, tenant: Tenant) -> None:
    """Put a superuser into ``tenant`` and log it."""
    request.session[ACTIVE_TENANT_KEY] = str(tenant.id)
    request.session[SUPPORT_VIEW_STARTED_KEY] = timezone.now().isoformat()
    logger.warning(
        "support view: user %s (%s) entered workspace %s (%s)",
        request.user.pk,
        request.user.email or request.user.username,
        tenant.slug,
        tenant.id,
    )


def leave_support_view(request) -> None:
    """Drop the support view. The middleware then falls back to the user's own
    first workspace on the next request."""
    if request.session.pop(SUPPORT_VIEW_STARTED_KEY, None) is not None:
        request.session.pop(ACTIVE_TENANT_KEY, None)


def resolve_support_tenant(request, tenant_id: uuid.UUID):
    """Return the tenant a superuser has switched into, or None.

    None means: not a superuser, the support view was never entered on this
    session (no marker), or the workspace no longer exists. In every None case
    the support-view session keys are cleared so the caller falls back to the
    user's own workspace.
    """
    if not request.user.is_superuser:
        return None
    if SUPPORT_VIEW_STARTED_KEY not in request.session:
        return None
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        _clear(request.session)
        return None
    return tenant


def log_support_write(request, response) -> None:
    """Record a write made while the support view is on. Each line stands on
    its own: who (id and email), what (method and path), where (workspace slug
    and id), outcome. The timestamp comes from the logging formatter."""
    if request.method not in WRITE_METHODS:
        return
    tenant = request.tenant
    logger.warning(
        "support view write: user %s (%s) %s %s in workspace %s (%s) -> %s",
        request.user.pk,
        request.user.email or request.user.username,
        request.method,
        request.path,
        tenant.slug,
        tenant.id,
        response.status_code,
    )


def _clear(session) -> None:
    session.pop(SUPPORT_VIEW_STARTED_KEY, None)
    session.pop(ACTIVE_TENANT_KEY, None)
