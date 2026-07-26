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

import requests
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

# A state only has to survive one hop out to GitHub and back. Keeping it short
# stops a captured state from being replayed indefinitely.
INSTALL_STATE_MAX_AGE = 600  # seconds


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


def _state_is_acceptable(request, tenant) -> bool:
    """Validate the install ``state`` when one is present.

    The state identifies *who started the flow*; it says nothing about which
    installation came back, so it is a targeting token and never an entitlement
    check (see ``_user_is_entitled``). A state-less callback is legitimate — it
    is what an install started from github.com looks like — but a state that is
    present and wrong means tampering, so reject it.
    """
    raw_state = request.GET.get("state", "")
    if not raw_state:
        return True

    try:
        payload = signing.loads(
            raw_state, salt=INSTALL_STATE_SALT, max_age=INSTALL_STATE_MAX_AGE
        )
    except signing.SignatureExpired:
        logger.warning("GitHub App callback with an expired state token.")
        messages.error(request, "This install request has expired. Please try again.")
        return False
    except signing.BadSignature:
        logger.warning("GitHub App callback with an invalid state token.")
        messages.error(request, "Invalid or expired install request.")
        return False

    if payload.get("tenant_id") != str(tenant.id) or payload.get("user_id") != str(
        request.user.id
    ):
        logger.warning(
            "GitHub App callback state mismatch: state=%s request tenant=%s user=%s",
            payload,
            tenant.id,
            request.user.id,
        )
        messages.error(request, "This install request was not initiated by you.")
        return False
    return True


def _user_is_entitled(request, installation_id: int) -> bool:
    """Confirm with GitHub that this user may access this installation.

    ``installation_id`` arrives as a query parameter, so it is attacker-chosen
    until proven otherwise: the App JWT can read *every* installation of this
    App, which would let any workspace attach any organization's repositories.
    The only authority on access is GitHub, asked with a user-to-server token.
    """
    if not (settings.GITHUB_APP_CLIENT_ID and settings.GITHUB_APP_CLIENT_SECRET):
        logger.error(
            "GitHub App OAuth credentials are not configured; refusing to "
            "connect installation %s without an entitlement check.",
            installation_id,
        )
        messages.error(
            request,
            "GitHub App connections aren't fully configured. Please contact your "
            "administrator.",
        )
        return False

    code = request.GET.get("code", "")
    if not code:
        logger.warning(
            "GitHub App callback without an authorization code for installation %s.",
            installation_id,
        )
        messages.error(
            request,
            "Couldn't verify your access to that installation. Please start the "
            "install from your workspace settings.",
        )
        return False

    try:
        user_token = github_app.exchange_user_code(code)
        allowed = github_app.user_can_access_installation(user_token, installation_id)
    except (github_app.UserAuthError, requests.RequestException):
        logger.exception(
            "GitHub App entitlement check failed for installation %s.", installation_id
        )
        messages.error(request, "Couldn't verify your access with GitHub. Please try again.")
        return False

    if not allowed:
        logger.warning(
            "User %s attempted to connect installation %s they cannot access.",
            request.user.id,
            installation_id,
        )
        messages.error(
            request,
            "You don't have access to that GitHub installation.",
        )
    return allowed


@login_required
def github_app_callback(request):
    """Handle GitHub's redirect back after an install.

    Accepts the installation only once GitHub confirms the signed-in user may
    access it, then records a tenant-scoped GitHub App connection. Any number of
    workspaces may connect the same installation — each is an independent grant
    by someone GitHub says has access.
    """
    _require_app_enabled()

    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    if not _admin_membership(request):
        messages.error(request, "You don't have permission to add a connection.")
        return redirect("tenant_settings")

    if not _state_is_acceptable(request, tenant):
        return redirect("tenant_settings")

    installation_id = request.GET.get("installation_id")
    if not installation_id:
        messages.error(request, "GitHub did not return an installation id.")
        return redirect("tenant_settings")

    try:
        installation_id = int(installation_id)
    except (TypeError, ValueError):
        messages.error(request, "GitHub returned an unreadable installation id.")
        return redirect("tenant_settings")

    if not _user_is_entitled(request, installation_id):
        return redirect("tenant_settings")

    installation = github_app.get_installation(installation_id)
    account = installation.get("account", {}) or {}
    account_login = account.get("login", "")
    account_type = account.get("type", "")

    connection, created = PlatformConnection.objects.update_or_create(
        tenant=tenant,
        platform=Platform.GITHUB,
        installation_id=installation_id,
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
