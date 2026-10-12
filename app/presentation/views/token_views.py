"""API tokens: personal ones on the profile page, workspace ones (admins
only) on the workspace settings page. The raw token is flashed once through
the session and never stored."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from app.domain.models import APIToken
from app.workspace_access import is_workspace_admin

WORKSPACE_TOKENS_URL = "tenant_settings"
WORKSPACE_TOKENS_ANCHOR = "#section-api-tokens"


def _flash_token(request, token: APIToken, raw: str) -> None:
    request.session["new_token_value"] = raw
    request.session["new_token_name"] = token.name


def _token_name(request) -> str:
    return request.POST.get("token_name", "").strip()[:100]


def _workspace_tokens(request):
    return redirect(reverse(WORKSPACE_TOKENS_URL) + WORKSPACE_TOKENS_ANCHOR)


@login_required
@require_POST
def create_personal_token(request):
    name = _token_name(request)
    if not name:
        messages.error(request, "Token name is required.")
        return redirect("profile")
    token, raw = APIToken.issue(name=name, created_by=request.user, user=request.user)
    _flash_token(request, token, raw)
    return redirect("profile")


@login_required
@require_POST
def revoke_personal_token(request, token_id):
    token = get_object_or_404(
        APIToken, id=token_id, kind=APIToken.Kind.PERSONAL, user=request.user
    )
    token.delete()
    messages.success(request, f'Token "{token.name}" revoked.')
    return redirect("profile")


@login_required
@require_POST
def create_workspace_token(request):
    tenant = request.tenant
    if not tenant or not is_workspace_admin(request):
        messages.error(request, "Only workspace admins can create workspace tokens.")
        return _workspace_tokens(request)
    name = _token_name(request)
    if not name:
        messages.error(request, "Token name is required.")
        return _workspace_tokens(request)
    token, raw = APIToken.issue(name=name, created_by=request.user, tenant=tenant)
    _flash_token(request, token, raw)
    return _workspace_tokens(request)


@login_required
@require_POST
def revoke_workspace_token(request, token_id):
    tenant = request.tenant
    if not tenant or not is_workspace_admin(request):
        messages.error(request, "Only workspace admins can revoke workspace tokens.")
        return _workspace_tokens(request)
    token = get_object_or_404(
        APIToken, id=token_id, kind=APIToken.Kind.WORKSPACE, tenant=tenant
    )
    token.delete()
    messages.success(request, f'Token "{token.name}" revoked.')
    return _workspace_tokens(request)
