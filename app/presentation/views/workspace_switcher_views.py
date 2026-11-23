"""The navbar workspace switcher.

The dropdown lazy-loads its rows from here the first time it opens, and the
search box re-queries with ``?q=``. Rows come only from the user's own
memberships — this view is the one place a foreign workspace could leak into
the switcher, so the membership filter is not optional. The single exception
is a superuser, who may switch into any workspace (the support view) and so
sees every workspace, with the ones they are not a member of marked.

Rows are grouped by ``PickerSection``: pinned first, then the user's own
workspaces, then support workspaces last.
"""
from itertools import groupby

from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef, Q
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from app.application.workspace_pins import PinNotAllowed, toggle_pin
from app.domain.models import Membership, Tenant, WorkspacePin
from app.domain.workspace_picker import PickerSection
from app.workspace_access import parse_tenant_id

# Rows rendered per response. Past this the partial says "N more — keep typing".
ROW_LIMIT = 20


@login_required
@require_GET
def workspace_switcher_list(request):
    return _render_list(request, request.GET.get("q", ""))


@login_required
@require_POST
def toggle_workspace_pin(request):
    """Pin or unpin a workspace, then re-render the rows (keeping the
    search) so the row moves into or out of the pinned section in place."""
    tenant_id = parse_tenant_id(request.POST.get("tenant_id"))
    if tenant_id is None:
        raise Http404
    try:
        toggle_pin(request.user, tenant_id)
    except PinNotAllowed:
        raise Http404
    return _render_list(request, request.POST.get("q", ""))


def _render_list(request, q):
    q = q.strip()
    current = request.tenant

    if request.user.is_superuser:
        tenants = Tenant.objects.all()
    else:
        tenants = Tenant.objects.filter(memberships__user=request.user)
    if q:
        tenants = tenants.filter(Q(name__icontains=q) | Q(slug__icontains=q))
    tenants = tenants.annotate(
        is_member=Exists(
            Membership.objects.filter(user=request.user, tenant=OuterRef("pk"))
        ),
        is_pinned=Exists(
            WorkspacePin.objects.filter(user=request.user, tenant=OuterRef("pk"))
        ),
    )
    total = tenants.count()

    current_tenant = tenants.filter(id=current.id).first() if current else None

    # Same order as PickerSection: pinned, then member, then support.
    others = tenants.order_by("-is_pinned", "-is_member", "name")
    if current:
        others = others.exclude(id=current.id)
    others = list(others[:ROW_LIMIT])

    sections = [
        (section, list(rows))
        for section, rows in groupby(
            others, key=lambda t: PickerSection.of(pinned=t.is_pinned, member=t.is_member)
        )
    ]

    shown = (1 if current_tenant else 0) + len(others)
    return render(
        request,
        "partials/workspace_switcher_list.html",
        {
            "q": q,
            "current_tenant": current_tenant,
            "sections": sections,
            "show_section_titles": bool(current_tenant) or len(sections) > 1,
            "remaining": max(total - shown, 0),
            "total": total,
        },
    )
