"""The admin dashboard (/staff/): GitGrit-wide administration for
superusers, in settings-style sections: the access-request queue and the
superusers themselves. Actions answer in place over HTMX (a toast and the
affected block drawn again); without JS they post and redirect."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_htmx.http import HttpResponseClientRedirect

from app.application import superuser_service
from app.application.access import (
    approve_access_request,
    onboarding_form_required,
    reject_access_request,
)
from app.domain.models import AccessRequest, Membership, Tenant
from app.domain.superusers import SuperuserRuleError
from app.domain.workspace_roles import MembershipRuleError
from app.presentation.htmx import toast
from app.workspace_access import parse_tenant_id

User = get_user_model()

STATUS_TABS = ("pending", "approved", "rejected", "all")


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied()


def _ACCESS_REQUESTS_URL():
    return reverse("admin_dashboard") + "#section-access-requests"


def _SUPERUSERS_URL():
    return reverse("admin_dashboard") + "#section-superusers"


@login_required
def admin_dashboard(request):
    _require_superuser(request)
    context = access_requests_context(request.GET.get("status", "pending"))
    context.update(superusers_context(request.user))
    return render(request, "pages/admin_dashboard.html", context)


@login_required
def access_request_list(request):
    """The old address of the queue (still in emails): now a dashboard tab."""
    _require_superuser(request)
    status = request.GET.get("status", "pending")
    return redirect(f"{reverse('admin_dashboard')}?status={status}#section-access-requests")


@login_required
def access_request_tab(request):
    """One status tab of the queue, swapped in place."""
    _require_superuser(request)
    return render(
        request,
        "components/access_requests_section.html",
        access_requests_context(request.GET.get("status", "pending")),
    )


# --- access requests ------------------------------------------------------


def _pending_count():
    return AccessRequest.objects.filter(status=AccessRequest.Status.PENDING).count()


def _tabs(pending):
    # Only pending gets a count: it is the one tab that asks for action.
    return [(tab, pending if tab == "pending" else None) for tab in STATUS_TABS]


def access_requests_context(status):
    if status not in STATUS_TABS:
        status = "pending"
    requests_ = AccessRequest.objects.select_related(
        "user", "reviewed_by"
    ).prefetch_related("user__socialaccount_set")
    if status != "all":
        requests_ = requests_.filter(status=status)
    return {
        "access_requests": requests_,
        "status": status,
        "tabs": _tabs(_pending_count()),
        "onboarding_form_required": onboarding_form_required(),
        "workspaces": Tenant.objects.order_by("name"),
        "roles": Membership.Role.choices,
    }


@login_required
@require_POST
def review_access_request(request, pk, decision):
    _require_superuser(request)
    access_request = get_object_or_404(
        AccessRequest.objects.select_related("user"), pk=pk
    )
    email = access_request.user.email
    if not access_request.is_pending:
        return _reviewed(request, access_request, f"{email} was already {access_request.status}.", "info")

    if decision == "reject":
        reject_access_request(access_request, request.user)
        return _reviewed(request, access_request, f"Rejected {email}.")

    # Approving puts the person in a workspace: an existing one, or a new one
    # for their company. There is no approving into nothing.
    role = request.POST.get("role", "")
    workspace, new_name = None, ""
    if request.POST.get("workspace_mode") == "existing":
        workspace = Tenant.objects.filter(pk=parse_tenant_id(request.POST.get("workspace_id"))).first()
        if workspace is None:
            return _not_reviewed(request, f"Pick the workspace {email} should join.")
    else:
        new_name = request.POST.get("workspace_name", "").strip()[:255]
        if not new_name:
            return _not_reviewed(request, f"Name the new workspace for {email}.")

    try:
        workspace = approve_access_request(
            access_request,
            request.user,
            role=role,
            workspace=workspace,
            new_workspace_name=new_name,
        )
    except MembershipRuleError as e:
        return _not_reviewed(request, str(e))
    return _reviewed(
        request, access_request, f"Approved {email} into {workspace.name} as {role}."
    )


def _reviewed(request, access_request, text, level="success"):
    """Answer a review. Over HTMX: the card leaves the pending tab (or is
    drawn again, reviewed, on the others) and the pending counts update.
    Without JS: a flash message and the list again."""
    if not request.htmx:
        getattr(messages, level)(request, text)
        return redirect(_ACCESS_REQUESTS_URL())
    tab = request.POST.get("tab", "pending")
    access_request.refresh_from_db()
    pending = _pending_count()
    context = {
        "ar": access_request,
        "status": tab,
        "oob": True,
        "tabs": _tabs(pending),
        "pending_access_requests": pending,
    }
    html = "" if tab == "pending" else render_to_string(
        "components/access_request_card.html", context, request
    )
    if tab == "pending" and not pending:
        html += (
            '<div id="access-request-cards" hx-swap-oob="true" class="text-center py-16 '
            'text-base-content/60">No one is waiting. New signups land here.</div>'
        )
    html += render_to_string("components/access_request_tabs.html", context, request)
    for badge_id in ("access-requests-badge", "admin-nav-requests-badge"):
        html += render_to_string(
            "components/access_requests_badge.html", {**context, "badge_id": badge_id}, request
        )
    return toast(HttpResponse(html), text, level)


def _not_reviewed(request, text):
    """The review didn't happen: say why, and leave the page as it is."""
    if not request.htmx:
        messages.error(request, text)
        return redirect(_ACCESS_REQUESTS_URL())
    response = toast(HttpResponse(""), text, "error")
    response["HX-Reswap"] = "none"
    return response


# --- superusers -----------------------------------------------------------


def superusers_context(user):
    supers = superuser_service.current()
    superusers = list(
        User.objects.filter(is_superuser=True, is_active=True)
        .select_related("superuser_granted_by")
        .order_by("superuser_granted_at", "date_joined")
    )
    for su in superusers:
        su.revocable = supers.can_revoke(str(user.pk), superuser_service.account(su))
    candidates = (
        User.objects.filter(is_active=True, is_superuser=False)
        .exclude(email="")
        .order_by("email")
        .values_list("email", flat=True)
    )
    return {"superusers": superusers, "candidates": candidates}


@login_required
@require_POST
def grant_superuser(request):
    _require_superuser(request)
    email = request.POST.get("email", "").strip()
    target = User.objects.filter(email__iexact=email).first() if email else None
    if target is None:
        return _superusers_done(
            request, f"No user found with email {email}.", "error", grant_email=email
        )
    try:
        superuser_service.grant(target, request.user)
    except SuperuserRuleError as e:
        return _superusers_done(request, str(e), "error", grant_email=email)
    return _superusers_done(request, f"{target.email} is now a superuser.")


@login_required
@require_POST
def revoke_superuser(request, user_id):
    _require_superuser(request)
    target = get_object_or_404(User, pk=user_id)
    try:
        superuser_service.revoke(target, request.user)
    except SuperuserRuleError as e:
        return _superusers_done(request, str(e), "error")
    if target.pk == request.user.pk:
        # Stepping down takes this page away: a real navigation.
        messages.success(request, "You're no longer a superuser.")
        if request.htmx:
            return HttpResponseClientRedirect(reverse("dashboard"))
        return redirect("dashboard")
    return _superusers_done(request, f"{target.email} is no longer a superuser.")


def _superusers_done(request, text, level="success", **form_state):
    if not request.htmx:
        getattr(messages, level)(request, text)
        return redirect(_SUPERUSERS_URL())
    context = superusers_context(request.user)
    context.update(form_state)
    response = render(request, "components/superusers_panel.html", context)
    return toast(response, text, level)
