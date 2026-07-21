"""GitHub App install flow: initiation + callback.

These views are gated behind the ``GITHUB_APP_ENABLED`` feature flag (a disabled
flag makes them 404, i.e. unreachable) and behind OWNER/ADMIN membership, mirror
the existing connection-management views. The install ``state`` is a signed
token (``django.core.signing``) carrying the tenant/user so the callback can
verify the round-trip was initiated by the same user in the same workspace.
"""
from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import Http404
from django.shortcuts import redirect

from app.domain.models import AuthMethod, Membership, Platform, PlatformConnection
from app.infrastructure import github_app

logger = logging.getLogger(__name__)

# Namespace for the signed install-state token.
INSTALL_STATE_SALT = "github-app-install-state"


def _require_app_enabled():
    if not settings.GITHUB_APP_ENABLED:
        raise Http404("GitHub App integration is not enabled.")


def _admin_membership(request):
    """Return the request user's OWNER/ADMIN membership for the active tenant,
    or None."""
    tenant = request.tenant
    if not tenant:
        return None
    membership = Membership.objects.filter(
        user=request.user, tenant=tenant
    ).first()
    if not membership or membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        return None
    return membership


@login_required
def github_app_install(request):
    """Redirect the admin to GitHub to install the shared App, carrying a signed
    ``state`` that identifies the initiating tenant + user."""
    _require_app_enabled()

    membership = _admin_membership(request)
    if not membership:
        messages.error(
            request, "You don't have permission to install the GitHub App."
        )
        return redirect("tenant_settings")

    state = signing.dumps(
        {
            "tenant_id": str(request.tenant.id),
            "user_id": str(request.user.id),
            "nonce": secrets.token_urlsafe(16),
        },
        salt=INSTALL_STATE_SALT,
    )
    url = (
        f"https://github.com/apps/{settings.GITHUB_APP_SLUG}"
        f"/installations/new?state={state}"
    )
    return redirect(url)


@login_required
def github_app_callback(request):
    """Handle GitHub's redirect back after an install.

    Verifies the signed ``state`` was issued for *this* logged-in user in *this*
    workspace (rejecting tampered or foreign state), confirms the installation
    with GitHub, then records a tenant-scoped GitHub App connection.
    """
    _require_app_enabled()

    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    raw_state = request.GET.get("state", "")
    try:
        payload = signing.loads(raw_state, salt=INSTALL_STATE_SALT)
    except signing.BadSignature:
        logger.warning("GitHub App callback with an invalid state token.")
        messages.error(request, "Invalid or expired install request.")
        return redirect("tenant_settings")

    # The state must belong to the current user + workspace — reject a state
    # replayed by (or against) a different tenant/user.
    if payload.get("tenant_id") != str(tenant.id) or payload.get(
        "user_id"
    ) != str(request.user.id):
        logger.warning(
            "GitHub App callback state mismatch: state=%s request tenant=%s user=%s",
            payload,
            tenant.id,
            request.user.id,
        )
        messages.error(request, "This install request was not initiated by you.")
        return redirect("tenant_settings")

    installation_id = request.GET.get("installation_id")
    if not installation_id:
        messages.error(request, "GitHub did not return an installation id.")
        return redirect("tenant_settings")

    installation = github_app.get_installation(int(installation_id))
    account = installation.get("account", {}) or {}
    account_login = account.get("login", "")
    account_type = account.get("type", "")

    connection, created = PlatformConnection.objects.update_or_create(
        tenant=tenant,
        platform=Platform.GITHUB,
        installation_id=int(installation_id),
        defaults={
            "auth_method": AuthMethod.GITHUB_APP,
            "display_name": f"GitHub App ({account_login})" if account_login else "GitHub App",
            "account_login": account_login,
            "account_type": account_type,
        },
    )
    messages.success(
        request,
        f'GitHub App {"connected" if created else "updated"} for '
        f'{account_login or "your account"}.',
    )
    return redirect("tenant_settings")
