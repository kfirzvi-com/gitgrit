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
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from app.domain.models import AuthMethod, Membership, Platform, PlatformConnection
from app.infrastructure import github_app

logger = logging.getLogger(__name__)

# Namespace for the signed install-state token.
INSTALL_STATE_SALT = "github-app-install-state"

# A state only has to survive one hop out to GitHub and back. Keeping it short
# stops a captured state from being replayed indefinitely.
INSTALL_STATE_MAX_AGE = 600  # seconds

# Where an entitlement-verified installation waits for the user to confirm which
# workspace it belongs to. Written only after GitHub vouches for the user, so
# the confirm POST never has to trust anything the client sent.
PENDING_INSTALL_SESSION_KEY = "pending_github_installation"


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


def _record_connection(tenant, installation_id: int, account_login: str, account_type: str):
    """Create or refresh this workspace's connection to an installation.

    Scoped to the tenant, so several workspaces can hold the same installation
    side by side — each one an independent grant by someone with access.
    """
    return PlatformConnection.objects.update_or_create(
        tenant=tenant,
        platform=Platform.GITHUB,
        installation_id=installation_id,
        defaults={
            "auth_method": AuthMethod.GITHUB_APP,
            "display_name": (
                f"GitHub App ({account_login})" if account_login else "GitHub App"
            ),
            "account_login": account_login,
            "account_type": account_type,
        },
    )


def _existing_connection(tenant, installation_id: int):
    return PlatformConnection.objects.filter(
        tenant=tenant,
        platform=Platform.GITHUB,
        auth_method=AuthMethod.GITHUB_APP,
        installation_id=installation_id,
    ).first()


def _refresh_without_code(request, tenant, installation_id: int):
    """Handle a return trip that carries no authorization code.

    Reconfiguring an existing install comes back via ``setup_on_update`` without
    re-running user authorization, so there is no code to prove entitlement
    with. That is only safe when this workspace already holds the installation:
    refreshing grants nothing it did not already have. Otherwise send them back
    to start an install properly, without hinting whether the installation
    exists or who else might hold it.
    """
    connection = _existing_connection(tenant, installation_id)
    if not connection:
        messages.info(
            request,
            "To connect a GitHub App installation, start from Install GitHub App "
            "in your workspace settings.",
        )
        return redirect("tenant_settings")

    installation = github_app.get_installation(installation_id)
    account = installation.get("account", {}) or {}
    _record_connection(
        tenant,
        installation_id,
        account.get("login", ""),
        account.get("type", ""),
    )
    messages.success(request, "GitHub App connection updated.")
    return redirect("tenant_settings")


@login_required
def github_app_callback(request):
    """Handle GitHub's redirect back after an install.

    Two shapes arrive here. An install started from workspace settings carries a
    signed ``state``, so the target workspace is already known and the
    connection is made outright. An install started from github.com carries no
    state — nothing tied that visit to a workspace — so the verified
    installation is parked in the session and the user confirms where it goes.

    Either way the installation itself is only accepted once GitHub confirms the
    signed-in user may access it.
    """
    _require_app_enabled()

    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    if not _admin_membership(request):
        messages.error(request, "You don't have permission to add a connection.")
        return redirect("tenant_settings")

    # A member without install rights can only *request* one from an org owner;
    # there is no installation yet, so report it rather than erroring on the id.
    if request.GET.get("setup_action") == "request":
        messages.info(
            request,
            "Your install request was sent to the organization's owners. "
            "Connect it here once they approve.",
        )
        return redirect("tenant_settings")

    if not _state_is_acceptable(request, tenant):
        return redirect("tenant_settings")

    raw_installation_id = request.GET.get("installation_id")
    if not raw_installation_id:
        messages.error(request, "GitHub did not return an installation id.")
        return redirect("tenant_settings")

    try:
        installation_id = int(raw_installation_id)
    except (TypeError, ValueError):
        messages.error(request, "GitHub returned an unreadable installation id.")
        return redirect("tenant_settings")

    if not request.GET.get("code"):
        return _refresh_without_code(request, tenant, installation_id)

    if not _user_is_entitled(request, installation_id):
        return redirect("tenant_settings")

    installation = github_app.get_installation(installation_id)
    account = installation.get("account", {}) or {}
    account_login = account.get("login", "")
    account_type = account.get("type", "")

    # A valid state means the user already chose the workspace on the way out —
    # don't ask them again.
    if request.GET.get("state"):
        _, created = _record_connection(
            tenant, installation_id, account_login, account_type
        )
        messages.success(
            request,
            f'GitHub App {"connected" if created else "updated"} for '
            f'{account_login or "your account"}.',
        )
        return redirect("tenant_settings")

    request.session[PENDING_INSTALL_SESSION_KEY] = {
        "installation_id": installation_id,
        "account_login": account_login,
        "account_type": account_type,
    }
    return render(
        request,
        "pages/github_app_confirm.html",
        {
            "account_login": account_login,
            "account_type": account_type,
            "target_tenant": tenant,
            "already_connected": bool(_existing_connection(tenant, installation_id)),
        },
    )


@login_required
@require_POST
def github_app_confirm(request):
    """Attach the installation the verified callback parked in the session.

    Reads the installation from the session rather than the request: the GET
    that wrote it had already proven this user may access it, so nothing the
    client sends here can widen what gets connected.
    """
    _require_app_enabled()

    tenant = request.tenant
    if not tenant or not _admin_membership(request):
        messages.error(request, "You don't have permission to add a connection.")
        return redirect("tenant_settings")

    pending = request.session.pop(PENDING_INSTALL_SESSION_KEY, None)
    if not pending:
        messages.error(
            request, "That install request has expired. Please try again."
        )
        return redirect("tenant_settings")

    _, created = _record_connection(
        tenant,
        pending["installation_id"],
        pending.get("account_login", ""),
        pending.get("account_type", ""),
    )
    messages.success(
        request,
        f'GitHub App {"connected" if created else "updated"} for '
        f'{pending.get("account_login") or "your account"}.',
    )
    return redirect("tenant_settings")
