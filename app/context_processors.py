from django.conf import settings

from app.domain.models import Tenant


def tenant_context(request):
    ctx = {
        "airgapped": settings.AIRGAPPED,
    }

    if not hasattr(request, "user") or not request.user.is_authenticated:
        return ctx

    ctx.update({
        "current_tenant": getattr(request, "tenant", None),
        "user_tenants": Tenant.objects.filter(
            memberships__user=request.user
        ).order_by("created_at"),
    })
    return ctx
