from app.domain.models import Membership
from app.workspace_access import (
    ACTIVE_TENANT_KEY,
    SUPPORT_VIEW_STARTED_KEY,
    log_support_write,
    parse_tenant_id,
    resolve_support_tenant,
)

EXEMPT_PREFIXES = ("/admin/", "/accounts/", "/api/webhooks/", "/static/")


class TenantMiddleware:
    """Resolve ``request.tenant`` (the active workspace) from the session.

    The session's ``active_tenant_id`` is trusted only when a ``Membership``
    row backs it. A superuser in the support view is the one exception: for
    them the id is resolved directly, and ``request.tenant_is_support_view``
    is set so templates and views can tell. Anything else falls back to the
    user's oldest own workspace.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.tenant_is_support_view = False

        if not request.user.is_authenticated or request.path.startswith(
            EXEMPT_PREFIXES
        ):
            return self.get_response(request)

        raw_id = request.session.get(ACTIVE_TENANT_KEY)
        active_tenant_id = parse_tenant_id(raw_id)
        if raw_id and active_tenant_id is None:
            # Garbage in the session (hand-edited, or an old format). Drop it
            # instead of letting the UUID field raise.
            request.session.pop(ACTIVE_TENANT_KEY, None)

        membership = None
        if active_tenant_id:
            membership = (
                Membership.objects.filter(
                    user=request.user, tenant_id=active_tenant_id
                )
                .select_related("tenant")
                .first()
            )

        if membership is None and active_tenant_id:
            tenant = resolve_support_tenant(request, active_tenant_id)
            if tenant is not None:
                request.tenant = tenant
                request.tenant_is_support_view = True
                response = self.get_response(request)
                log_support_write(request, response)
                return response

        if membership is None:
            membership = (
                Membership.objects.filter(user=request.user)
                .select_related("tenant")
                .order_by("tenant__created_at")
                .first()
            )

        if membership:
            request.tenant = membership.tenant
            request.session[ACTIVE_TENANT_KEY] = str(membership.tenant.id)
            # A real membership is never a support view; a leftover timestamp
            # would only make the next foreign id look pre-authorised.
            if SUPPORT_VIEW_STARTED_KEY in request.session:
                request.session.pop(SUPPORT_VIEW_STARTED_KEY, None)

        return self.get_response(request)
