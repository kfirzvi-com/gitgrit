"""The invitee's side of an invitation (app.application.invitations).

The emailed link (/invitations/<token>/) shows who invited them to what. A
signed-in invitee accepts or declines there. Someone signed out signs in, or
signs up: the link's token is kept in the session, and the sign-in and
sign-up paths (EmailAwareLoginView, the allauth adapters) take the
invitation from there. Signing up through it is accepting it. A signed-in
person also sees their open invitations in a banner and can act on them
there, which needs a confirmed address since there's no link.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from app.application import invitations
from app.domain.models import InvitationError, WorkspaceInvitation
from app.presentation.auth_adapters import INVITATION_SESSION_KEY
from app.presentation.htmx import toast
from app.workspace_access import ACTIVE_TENANT_KEY, leave_support_view

User = get_user_model()


def invitation(request, token):
    found = invitations.find_open(token)
    if found is None:
        request.session.pop(INVITATION_SESSION_KEY, None)
        return render(request, "pages/invitation.html", {"state": "gone"}, status=404)

    request.session[INVITATION_SESSION_KEY] = token
    context = {
        "invitation": found,
        "token": token,
        "role_label": found.get_role_display(),
        "inviter": found.invited_by,
        # Every way in comes back here, to accept.
        "redirect_field_name": "next",
        "redirect_field_value": request.path,
        "hide_invitation_banner": True,
    }
    if request.user.is_authenticated:
        mine = found.is_for(invitations.emails_of(request.user, via_link=True))
        context["state"] = "accept" if mine else "wrong_account"
    else:
        has_account = User.objects.filter(email__iexact=found.email).exists()
        context["state"] = "sign_in" if has_account else "sign_up"
    return render(request, "pages/invitation.html", context)


@login_required
@require_POST
def accept_invitation(request, token):
    found = invitations.find_open(token)
    if found is None:
        messages.error(request, "This invitation is no longer valid.")
        return redirect("dashboard")
    return _accept(request, found, via_link=True, back=("invitation", token))


@login_required
@require_POST
def decline_invitation(request, token):
    found = invitations.find_open(token)
    if found is not None:
        try:
            invitations.decline(found, request.user, via_link=True)
        except InvitationError as e:
            messages.error(request, str(e))
            return redirect("invitation", token)
        messages.info(request, f"You declined the invitation to {found.tenant.name}.")
    request.session.pop(INVITATION_SESSION_KEY, None)
    return redirect("dashboard")


@login_required
@require_POST
def accept_invitation_in_app(request, pk):
    found = get_object_or_404(WorkspaceInvitation, pk=pk)
    return _accept(request, found, via_link=False, back=("dashboard",))


@login_required
@require_POST
def decline_invitation_in_app(request, pk):
    found = get_object_or_404(WorkspaceInvitation, pk=pk)
    try:
        invitations.decline(found, request.user, via_link=False)
        text, level = f"You declined the invitation to {found.tenant.name}.", "info"
    except InvitationError as e:
        text, level = str(e), "error"
    if request.htmx:
        # The banner row goes; nothing else on the page changes.
        return toast(HttpResponse(""), text, level)
    getattr(messages, level)(request, text)
    return redirect("dashboard")


def _accept(request, found, *, via_link, back):
    try:
        invitations.accept(found, request.user, via_link=via_link)
    except InvitationError as e:
        messages.error(request, str(e))
        return redirect(*back)
    enter_workspace(request, found)
    messages.success(request, f"Welcome to {found.tenant.name}.")
    return redirect("dashboard")


def enter_workspace(request, found):
    """After accepting: drop the invitation from the session and land in the
    workspace just joined."""
    request.session.pop(INVITATION_SESSION_KEY, None)
    leave_support_view(request)
    request.session[ACTIVE_TENANT_KEY] = str(found.tenant_id)


def sign_up_from_invitation(request, found, email, password):
    """EmailAwareLoginView's sign-up, when the email is the one invited: an
    active account, in the workspace, signed in."""
    user = invitations.sign_up_and_accept(found, email, password)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    enter_workspace(request, found)
    messages.success(request, f"Welcome to GitGrit. You're in {found.tenant.name}.")
    return redirect("dashboard")
