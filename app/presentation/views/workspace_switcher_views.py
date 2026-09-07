"""The navbar workspace switcher.

The dropdown lazy-loads its rows from here the first time it opens, and the
search box re-queries with ``?q=``. Rows come only from the user's own
memberships — this view is the one place a foreign workspace could leak into
the switcher, so the membership filter is not optional.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from app.domain.models import Membership

# Rows rendered per response. Past this the partial says "N more — keep typing".
ROW_LIMIT = 20


@login_required
@require_GET
def workspace_switcher_list(request):
    q = request.GET.get("q", "").strip()
    current = request.tenant

    memberships = Membership.objects.filter(user=request.user).select_related("tenant")
    if q:
        memberships = memberships.filter(
            Q(tenant__name__icontains=q) | Q(tenant__slug__icontains=q)
        )
    total = memberships.count()

    current_membership = (
        memberships.filter(tenant=current).first() if current else None
    )

    others = memberships.order_by("tenant__name")
    if current:
        others = others.exclude(tenant=current)
    others = list(others[:ROW_LIMIT])

    shown = (1 if current_membership else 0) + len(others)
    return render(
        request,
        "partials/workspace_switcher_list.html",
        {
            "q": q,
            "current_membership": current_membership,
            "others": others,
            "remaining": max(total - shown, 0),
            "total": total,
        },
    )
