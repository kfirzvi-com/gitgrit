from app.domain.models import Membership

EXEMPT_PREFIXES = ("/admin/", "/accounts/", "/api/webhooks/", "/static/")


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None

        if not request.user.is_authenticated or request.path.startswith(
            EXEMPT_PREFIXES
        ):
            return self.get_response(request)

        active_tenant_id = request.session.get("active_tenant_id")

        membership = None
        if active_tenant_id:
            membership = (
                Membership.objects.filter(
                    user=request.user, tenant_id=active_tenant_id
                )
                .select_related("tenant")
                .first()
            )

        if not membership:
            membership = (
                Membership.objects.filter(user=request.user)
                .select_related("tenant")
                .order_by("tenant__created_at")
                .first()
            )

        if membership:
            request.tenant = membership.tenant
            request.session["active_tenant_id"] = str(membership.tenant.id)

        return self.get_response(request)
