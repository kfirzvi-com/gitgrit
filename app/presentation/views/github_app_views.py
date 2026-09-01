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

import jwt
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

# Where the installations GitHub vouched for wait while the user picks one.
# Same reasoning as above: written only after GitHub answered, so the POST that
# follows takes only the choice from the client, never the candidates.
PENDING_CHOICES_SESSION_KEY = "github_installation_choices"


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


def _sign_state(request) -> str:
    return signing.dumps(
        {
            "tenant_id": str(request.tenant.id),
            "user_id": str(request.user.id),
            "nonce": secrets.token_urlsafe(16),
        },
        salt=INSTALL_STATE_SALT,
    )


def install_url(state: str) -> str:
    """Where GitHub sets the App up on an account it isn't installed on yet."""
    return (
        f"https://github.com/apps/{settings.GITHUB_APP_SLUG}"
        f"/installations/new?state={state}"
    )


@login_required
def github_app_install(request):
    """Send the admin to GitHub to identify themselves, not to install.

    Asking GitHub to install is a one-shot: once the App is on an account,
    ``/installations/new`` stops producing a callback and drops the user on the
    App's settings page instead. A second workspace wanting that same
    organization — a supported arrangement, since each workspace holds its own
    grant — could then never connect it, and the flow dead-ended by telling
    them to press the button they had just pressed.

    Authorization has no such limit, so it is the entry point. Coming back with
    a code, we can ask GitHub which installations this person may reach and
    offer them: the ones already set up become a list to pick from, and
    installing on a new account stays one link away. Both roads end at a
    connection; the button no longer has to guess which one is wanted.
    """
    _require_app_enabled()

    membership = _admin_membership(request)
    if not membership:
        messages.error(
            request, "You don't have permission to install the GitHub App."
        )
        return redirect("tenant_settings")

    state = _sign_state(request)
    return redirect(
        "https://github.com/login/oauth/authorize"
        f"?client_id={settings.GITHUB_APP_CLIENT_ID}&state={state}"
    )


@login_required
def github_app_install_new(request):
    """Straight to GitHub's install page, for adding an account we don't have.

    Reached from the "install on another organization" link on the picker, and
    used as the fallback when a user can reach no installation at all.
    """
    _require_app_enabled()

    if not _admin_membership(request):
        messages.error(
            request, "You don't have permission to install the GitHub App."
        )
        return redirect("tenant_settings")

    return redirect(install_url(_sign_state(request)))


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


def _user_administers_the_account(
    request, user_token: str, installation_id: int
) -> bool:
    """Confirm this user administers the account the installation sits on.

    ``GET /user/installations`` — the check above — answers "can this user reach
    *anything* in this installation". GitHub lists an installation there as soon
    as the user has explicit read/write/admin on **one** of its repositories, so
    an outside collaborator on a single repo qualifies. A connection is not
    repository-shaped, though: it holds an installation, mints installation-wide
    tokens, and lists the installation's own repository set in Add Project. Read
    as installation-level permission, that one collaborator grant becomes read
    access to every private repository on the account.

    So the question asked here is the one GitHub itself asks before letting
    anyone install or uninstall the App: do you own this account? An owner is
    entitled to whatever their installation covers, including whatever is added
    to it tomorrow — which is why this is asked of the account and not of
    today's repository list, a snapshot that a single "add repository" undoes.

    Fails closed. The account is deliberately not named: the same refusal has to
    serve an installation belonging to someone else and one that does not exist.
    """
    try:
        administers = github_app.user_administers_installation(
            user_token, installation_id
        )
    except (requests.RequestException, jwt.InvalidKeyError):
        logger.exception(
            "Couldn't establish whether user %s administers installation %s.",
            request.user.id,
            installation_id,
        )
        messages.error(
            request,
            "Couldn't check your GitHub access to that installation. Please try again.",
        )
        return False

    if not administers:
        logger.warning(
            "Refusing installation %s for user %s: they don't administer its "
            "GitHub account.",
            installation_id,
            request.user.id,
        )
        messages.error(
            request,
            "Only an owner of that GitHub account can connect its installation "
            "to a workspace. Ask an owner to connect it instead.",
        )
        return False
    return True


def _user_is_entitled(request, installation_id: int) -> bool:
    """Confirm with GitHub that this user may access this installation.

    ``installation_id`` arrives as a query parameter, so it is attacker-chosen
    until proven otherwise: the App JWT can read *every* installation of this
    App, which would let any workspace attach any organization's repositories.
    The only authority on access is GitHub, asked with a user-to-server token.

    Two gates, and both matter. The installation must appear in the user's own
    installation list, which is what stops a foreign id being claimed outright;
    and the user must administer the account it sits on, which is what stops a
    partial grant being cashed in for the whole account.
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
        return False

    return _user_administers_the_account(request, user_token, installation_id)


def _fetch_account(request, installation_id: int):
    """Read the installation's account from GitHub, or None if it can't be read.

    GitHub answering with an error here is ordinary, not exceptional: a callback
    URL replayed after the installation was deleted 404s, and the API has its
    own bad days. Returning None lets the caller apologise and redirect instead
    of raising a 500 at someone mid-install.

    ``InvalidKeyError`` belongs here too: availability only checks that a private
    key is *present*, so a truncated or wrongly-escaped key gets the feature
    switched on and fails at the first signature.
    """
    try:
        installation = github_app.get_installation(installation_id)
    except (requests.RequestException, jwt.InvalidKeyError):
        logger.exception(
            "Couldn't read GitHub installation %s while completing an install.",
            installation_id,
        )
        messages.error(
            request,
            "Couldn't read that installation from GitHub. It may have been "
            "removed — please try installing again.",
        )
        return None
    account = installation.get("account") or {}
    return account.get("login", ""), account.get("type", "")


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

    account = _fetch_account(request, installation_id)
    if account is None:
        return redirect("tenant_settings")

    _record_connection(tenant, installation_id, *account)
    messages.success(request, "GitHub App connection updated.")
    return redirect("tenant_settings")


def _account_list(installations) -> str:
    """Join account logins for a message: "a", "a and b", "a, b and c"."""
    logins = [i.get("account_login") or f'installation {i["id"]}' for i in installations]
    if len(logins) == 1:
        return logins[0]
    return ", ".join(logins[:-1]) + f" and {logins[-1]}"


def _partition_by_authority(request, user_token: str, installations):
    """Split candidates into the ones this user may connect and the ones not.

    Returns ``(connectable, blocked)``, or ``None`` when GitHub could not be
    asked — a candidate we cannot vouch for must not be offered, and an outage
    is not something to report per row as though it were the user's access.

    One ``AccountAuthority`` serves the whole list, so the cost is at most two
    GitHub calls for the batch however many accounts the person belongs to.
    """
    authority = github_app.AccountAuthority(user_token)
    connectable, blocked = [], []
    try:
        for installation in installations:
            administers = authority.administers(
                installation.get("account_type", ""),
                installation.get("account_login", ""),
                installation.get("account_id"),
            )
            (connectable if administers else blocked).append(installation)
    except requests.RequestException:
        logger.exception(
            "Couldn't establish which GitHub accounts user %s administers while "
            "building the install picker.",
            request.user.id,
        )
        return None

    if blocked:
        logger.warning(
            "Withholding %d GitHub installation(s) from user %s: they don't "
            "administer the account.",
            len(blocked),
            request.user.id,
        )
    return connectable, blocked


def _offer_connectable_installations(request, tenant):
    """Ask GitHub what this person can connect, and offer it.

    GitHub answers per-user, so an installation missing from this list is one
    this user may not connect. Appearing in it is necessary but not sufficient:
    the endpoint lists any installation the user reaches *one* repository of,
    while a connection holds the whole installation — so each candidate is then
    held to the same account-ownership test the callback applies before it is
    offered. Held-back accounts are named, since the user already knows they
    exist (that is why they showed up at all).

    The survivors are parked in the session for the same reason a direct install
    is — the POST that follows then needs to trust nothing the client sends.
    That POST reads the session, so filtering only the rendered list would not
    be enough: a candidate stored but hidden is still connectable.

    Note the list says nothing about other workspaces. An account shows up
    because *this user* can reach it on GitHub, never because some other
    workspace connected it.
    """
    code = request.GET.get("code", "")
    try:
        user_token = github_app.exchange_user_code(code)
        installations = github_app.list_user_installations(user_token)
    except (github_app.UserAuthError, requests.RequestException):
        logger.exception("Couldn't list GitHub installations for user %s.", request.user.id)
        messages.error(
            request, "Couldn't check your GitHub access. Please try again."
        )
        return redirect("tenant_settings")

    if not installations:
        # Nothing to choose between — send them where something can happen.
        messages.info(
            request,
            "GitGrit isn't installed on any of your GitHub accounts yet. "
            "Choose one to install it on.",
        )
        return redirect(install_url(_sign_state(request)))

    partitioned = _partition_by_authority(request, user_token, installations)
    if partitioned is None:
        messages.error(request, "Couldn't check your GitHub access. Please try again.")
        return redirect("tenant_settings")
    installations, blocked = partitioned

    if not installations:
        messages.error(
            request,
            f"GitGrit is installed on {_account_list(blocked)}, but you don't "
            "own that account, so connecting it would give this workspace "
            "access you don't have. Ask an owner to connect it, or install "
            "GitGrit on an account you own.",
        )
        return redirect(install_url(_sign_state(request)))

    if blocked:
        messages.warning(
            request,
            f"Not offered: {_account_list(blocked)}. Only an owner of the "
            "account can connect a GitHub App installation to a workspace.",
        )

    already = set(
        PlatformConnection.objects.filter(
            tenant=tenant,
            platform=Platform.GITHUB,
            auth_method=AuthMethod.GITHUB_APP,
            installation_id__in=[i["id"] for i in installations],
        ).values_list("installation_id", flat=True)
    )

    request.session[PENDING_CHOICES_SESSION_KEY] = {
        "tenant_id": str(tenant.id),
        "installations": installations,
    }
    return render(
        request,
        "pages/github_app_choose.html",
        {
            "installations": [
                {**i, "already_connected": i["id"] in already} for i in installations
            ],
            "target_tenant": tenant,
        },
    )


@login_required
@require_POST
def github_app_choose(request):
    """Connect the installation picked from the list GitHub vouched for.

    Reads the candidates from the session rather than the request: the GET that
    wrote them had already proven this user may connect each one, so the only
    thing taken from the client here is *which* of them was chosen.
    """
    _require_app_enabled()

    tenant = request.tenant
    if not tenant or not _admin_membership(request):
        messages.error(request, "You don't have permission to add a connection.")
        return redirect("tenant_settings")

    pending = request.session.pop(PENDING_CHOICES_SESSION_KEY, None)
    if not pending:
        messages.error(request, "That request has expired. Please try again.")
        return redirect("tenant_settings")

    if pending.get("tenant_id") != str(tenant.id):
        logger.warning(
            "Discarding GitHub installation choices confirmed under a different "
            "workspace: pending=%s active=%s",
            pending.get("tenant_id"),
            tenant.id,
        )
        messages.error(
            request,
            "Your active workspace changed since that started. "
            "Please try again from the workspace you want it in.",
        )
        return redirect("tenant_settings")

    try:
        chosen_id = int(request.POST.get("installation_id", ""))
    except (TypeError, ValueError):
        messages.error(request, "Please choose an organization to connect.")
        return redirect("tenant_settings")

    chosen = next(
        (i for i in pending["installations"] if i["id"] == chosen_id), None
    )
    if chosen is None:
        logger.warning(
            "User %s posted installation %s that GitHub did not vouch for.",
            request.user.id,
            chosen_id,
        )
        messages.error(request, "You don't have access to that GitHub installation.")
        return redirect("tenant_settings")

    _, created = _record_connection(
        tenant,
        chosen["id"],
        chosen.get("account_login", ""),
        chosen.get("account_type", ""),
    )
    messages.success(
        request,
        f'GitHub App {"connected" if created else "updated"} for '
        f'{chosen.get("account_login") or "your account"}.',
    )
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
        # Authorization with nothing to install: this is the return trip from
        # github_app_install, and the interesting answer is which installations
        # this person can already reach.
        if request.GET.get("code"):
            return _offer_connectable_installations(request, tenant)
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

    account = _fetch_account(request, installation_id)
    if account is None:
        return redirect("tenant_settings")
    account_login, account_type = account

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

    # Records which workspace the confirm page is about to name. The user can
    # switch workspace in another tab before pressing the button, and attaching
    # an installation somewhere other than the page said would be a silent
    # surprise — so the POST re-checks this instead of trusting the session's
    # active tenant at that moment.
    request.session[PENDING_INSTALL_SESSION_KEY] = {
        "installation_id": installation_id,
        "account_login": account_login,
        "account_type": account_type,
        "tenant_id": str(tenant.id),
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

    if pending.get("tenant_id") != str(tenant.id):
        logger.warning(
            "Discarding a pending GitHub installation confirmed under a "
            "different workspace: pending=%s active=%s",
            pending.get("tenant_id"),
            tenant.id,
        )
        messages.error(
            request,
            "Your active workspace changed since that install started. "
            "Please install again from the workspace you want it in.",
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
