import logging

from django.shortcuts import redirect

from app.domain.models import Membership
from app.workspace_access import (
    ACTIVE_TENANT_KEY,
    SUPPORT_VIEW_STARTED_KEY,
    log_support_write,
    parse_tenant_id,
    resolve_support_tenant,
)

logger = logging.getLogger("app.access")

EXEMPT_PREFIXES = ("/admin/", "/accounts/", "/api/webhooks/", "/static/")

# Pages a signed-in user can use without being in any workspace. Everything
# else needs one, and sends a user who has none to the no-workspace page.
NO_WORKSPACE_PREFIXES = (
    "/api/",
    "/setup/",
    "/access/",
    "/staff/",
    "/profile/",
    "/no-workspace/",
    "/notifications/",
    "/feedback/",
    "/tenants/new/",
    "/tenants/switch/",
    "/tenants/switcher/",
)


class TenantMiddleware:
    """Resolve ``request.tenant`` (the active workspace) from the session.

    The session's ``active_tenant_id`` is trusted only when a ``Membership``
    row backs it. A user in no workspace at all is sent to the no-workspace
    page from anywhere that needs one. A superuser in the support view is the one exception: for
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
        elif not request.path.startswith(NO_WORKSPACE_PREFIXES):
            # Workspaces are handed out by admins, so a signed-in user can
            # be in none: approved before one was set up, or their last one
            # was deleted or left. No workspace page would work for them.
            return redirect("no_workspace")

        return self.get_response(request)


class FirstRunSetupMiddleware:
    """Send every page to first-run setup while the deployment has no users.

    Once a user exists the answer can never go back to "no users" in a way
    that matters, so each process stops asking after the first time it sees
    one. Until then it logs where to find the setup token, once per process.
    """

    EXEMPT_PREFIXES = ("/setup/", "/static/", "/api/")

    def __init__(self, get_response):
        self.get_response = get_response
        self.set_up = False
        self.hint_logged = False

    def __call__(self, request):
        if not self.set_up and not request.path.startswith(self.EXEMPT_PREFIXES):
            from app.application.access import setup_required

            if setup_required():
                self._log_hint()
                return redirect("first_run_setup")
            self.set_up = True
        return self.get_response(request)

    def _log_hint(self):
        if self.hint_logged:
            return
        from app.application.access import setup_token

        logger.warning(
            "GitGrit has no users yet. Open /setup/?token=%s to create the admin.",
            setup_token(),
        )
        self.hint_logged = True
