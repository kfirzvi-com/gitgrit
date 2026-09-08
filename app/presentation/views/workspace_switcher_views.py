"""The navbar workspace switcher.

The dropdown lazy-loads its rows from here the first time it opens, and the
search box re-queries with ``?q=``. Rows come only from the user's own
memberships — this view is the one place a foreign workspace could leak into
the switcher, so the membership filter is not optional. The single exception
is a superuser, who may switch into any workspace (the support view) and so
sees every workspace, with the ones they are not a member of marked.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from app.domain.models import Membership, Tenant

# Rows rendered per response. Past this the partial says "N more — keep typing".
ROW_LIMIT = 20


@login_required
@require_GET
def workspace_switcher_list(request):
    q = request.GET.get("q", "").strip()
    current = request.tenant

    member_tenant_ids = set(
        Membership.objects.filter(user=request.user).values_list("tenant_id", flat=True)
    )
    if request.user.is_superuser:
        tenants = Tenant.objects.all()
    else:
        tenants = Tenant.objects.filter(id__in=member_tenant_ids)
    if q:
        tenants = tenants.filter(Q(name__icontains=q) | Q(slug__icontains=q))
    total = tenants.count()

    current_tenant = tenants.filter(id=current.id).first() if current else None

    others = tenants.order_by("name")
    if current:
        others = others.exclude(id=current.id)
    others = list(others[:ROW_LIMIT])

    shown = (1 if current_tenant else 0) + len(others)
    return render(
        request,
        "partials/workspace_switcher_list.html",
        {
            "q": q,
            "current_tenant": current_tenant,
            "current_is_support": bool(
                current_tenant and current_tenant.id not in member_tenant_ids
            ),
            "others": others,
            "member_tenant_ids": member_tenant_ids,
            "remaining": max(total - shown, 0),
            "total": total,
        },
    )
