"""GitHub App authentication: mint short-lived installation tokens.

A single shared GitHub App (SaaS) authenticates as an *App* using a signed
JWT (RS256, signed with the App's private key), then exchanges that JWT for a
short-lived *installation* access token scoped to one installation (and
optionally a subset of repositories / permissions). Installation tokens are
cached in-process, keyed by ``(installation_id, scope)``, until shortly before
they expire so we don't mint a fresh one on every call.

No real GitHub App exists yet (Phase 0 is a manual human action); all HTTP
exchanges here are mocked in tests.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

import jwt
import requests
from django.conf import settings

GITHUB_API_BASE = "https://api.github.com"

# Seconds subtracted from a token's real expiry before we consider it stale, so
# a cached token never expires mid-request.
_EXPIRY_SAFETY_BUFFER = 60

# JWT lifetime: GitHub allows at most 10 minutes. We backdate ``iat`` slightly
# to tolerate clock skew and keep the total window under the 10-minute ceiling.
_JWT_BACKDATE = 60
_JWT_LIFETIME = 8 * 60

# In-process cache: {(installation_id, scope): (token, expires_at_epoch)}.
_token_cache: dict[tuple[int, str], tuple[str, float]] = {}
_cache_lock = threading.Lock()


def build_app_jwt() -> str:
    """Return a signed App JWT (RS256) for authenticating as the GitHub App."""
    now = int(time.time())
    payload = {
        "iat": now - _JWT_BACKDATE,
        "exp": now + _JWT_LIFETIME,
        "iss": settings.GITHUB_APP_ID,
    }
    return jwt.encode(payload, settings.GITHUB_APP_PRIVATE_KEY, algorithm="RS256")


def _app_headers() -> dict:
    return {
        "Authorization": f"Bearer {build_app_jwt()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _user_headers(user_token: str) -> dict:
    """Headers for a user-to-server request, i.e. one made *as the human*."""
    return {
        "Authorization": f"Bearer {user_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_names(repositories: list[str] | None) -> list[str] | None:
    """Normalize repository identifiers to the names GitHub expects.

    ``POST /app/installations/{id}/access_tokens`` scopes a token by repository
    name *relative to the installation* — ``"app"``, never ``"acme/app"``. Every
    caller here holds a project's ``full_path``, which is the owner-qualified
    form, so accept either and keep only the last segment. Passing a full path
    through is a 422 from GitHub, i.e. a standard run that never happens.
    """
    if not repositories:
        return None
    return [name.rsplit("/", 1)[-1] for name in repositories]


def _scope_key(repositories: list[str] | None) -> str:
    """Build a stable cache-scope string for a token request.

    Callers pass already-normalized names, so ``acme/app`` and ``app`` share one
    cache entry rather than minting two identical tokens.
    """
    if not repositories:
        return "all"
    return ",".join(sorted(repositories))


def _parse_expires_at(value: str) -> float:
    """Parse GitHub's ISO-8601 ``expires_at`` into an epoch float."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.timestamp()


def get_installation_token(
    installation_id: int,
    repositories: list[str] | None = None,
    permissions: dict | None = None,
) -> str:
    """Return an installation access token, minting + caching as needed.

    A cached token is reused while it is still valid (its real expiry minus a
    safety buffer); otherwise a fresh token is requested from GitHub.

    ``repositories`` may be given as owner-qualified paths (``acme/app``) or bare
    names; both are normalized to what GitHub accepts.
    """
    repo_names = _repo_names(repositories)
    scope = _scope_key(repo_names)
    cache_key = (installation_id, scope)

    with _cache_lock:
        cached = _token_cache.get(cache_key)
        if cached and cached[1] > time.time():
            return cached[0]

    body: dict = {}
    if repo_names:
        body["repositories"] = repo_names
    if permissions:
        body["permissions"] = permissions

    resp = requests.post(
        f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens",
        headers=_app_headers(),
        json=body,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    token = data["token"]
    expires_at = _parse_expires_at(data["expires_at"]) - _EXPIRY_SAFETY_BUFFER
    with _cache_lock:
        _token_cache[cache_key] = (token, expires_at)
    return token


def get_installation(installation_id: int) -> dict:
    """Return the installation object (GET /app/installations/{id})."""
    resp = requests.get(
        f"{GITHUB_API_BASE}/app/installations/{installation_id}",
        headers=_app_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class UserAuthError(Exception):
    """GitHub refused to issue a user-to-server token for the supplied code."""


def exchange_user_code(code: str) -> str:
    """Exchange an install/authorization ``code`` for a user-to-server token.

    The resulting token acts *as the human*, which is what makes it usable as
    proof of entitlement — unlike the App JWT, which can read every
    installation of this App.
    """
    resp = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.GITHUB_APP_CLIENT_ID,
            "client_secret": settings.GITHUB_APP_CLIENT_SECRET,
            "code": code,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        # GitHub reports OAuth failures as 200 + {"error": ...}.
        raise UserAuthError(data.get("error_description") or data.get("error") or "no access_token")
    return token


def list_user_installations(user_token: str) -> list[dict]:
    """Every installation of this App that GitHub says the user can reach.

    GitHub answers this per-user, so an installation missing from the list is
    one this user reaches nothing in and may certainly not connect. Appearing
    in it means only that: GitHub includes an installation as soon as the user
    has explicit read/write/admin on **one** of its repositories, so this is
    the candidate set, never the entitlement (see ``AccountAuthority``).
    Paginates, because a user can belong to many organizations.

    Returns ``[{"id", "account_id", "account_login", "account_type"}]``,
    flattened so callers don't reach into GitHub's payload shape.
    """
    headers = _user_headers(user_token)
    per_page = 100
    page = 1
    seen = 0
    found: list[dict] = []
    while True:
        resp = requests.get(
            f"{GITHUB_API_BASE}/user/installations",
            headers=headers,
            params={"per_page": per_page, "page": page},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        installations = data.get("installations", [])
        for item in installations:
            account = item.get("account") or {}
            found.append(
                {
                    "id": int(item.get("id", 0)),
                    "account_id": account.get("id"),
                    "account_login": account.get("login", ""),
                    "account_type": account.get("type", ""),
                }
            )
        seen += len(installations)
        if not installations or seen >= data.get("total_count", 0):
            return found
        page += 1


def user_can_access_installation(user_token: str, installation_id: int) -> bool:
    """Whether GitHub lists ``installation_id`` as accessible to this user.

    GitHub itself is the authority on who may reach an installation, so this is
    what stands between a workspace and someone else's repositories.
    """
    return any(
        item["id"] == installation_id for item in list_user_installations(user_token)
    )


def get_authenticated_user(user_token: str) -> dict:
    """The human behind a user-to-server token (``GET /user``).

    Needs no App permission, which is the point: an entitlement check that
    demanded one would have to be accepted afresh by every installation the
    App already has before it could run at all.
    """
    resp = requests.get(
        f"{GITHUB_API_BASE}/user",
        headers=_user_headers(user_token),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def list_user_org_roles(user_token: str) -> dict[str, str]:
    """This user's role in every organization they actively belong to.

    ``{lowered login: "admin" | "member" | "billing_manager"}``. ``admin`` is
    an organization owner — precisely who GitHub lets install and uninstall an
    App on the organization, since the App-manager role explicitly does not
    carry that right.

    ``GET /user/memberships/orgs`` works with a GitHub App user access token
    and requires no permission, unlike its per-organization sibling
    ``/user/memberships/orgs/{org}``, which needs "Members" read. One call
    answers for every organization at once, so the per-org form buys nothing.

    Memberships that are not ``active`` are dropped: an unaccepted invitation
    to own an organization is not ownership. The response is a plain array
    rather than a counted envelope, so a short page ends the walk.
    """
    per_page = 100
    page = 1
    roles: dict[str, str] = {}
    while True:
        resp = requests.get(
            f"{GITHUB_API_BASE}/user/memberships/orgs",
            headers=_user_headers(user_token),
            params={"per_page": per_page, "page": page},
            timeout=15,
        )
        resp.raise_for_status()
        memberships = resp.json()
        for membership in memberships:
            if membership.get("state") != "active":
                continue
            organization = membership.get("organization") or {}
            login = (organization.get("login") or "").lower()
            if login:
                roles[login] = membership.get("role", "")
        if len(memberships) < per_page:
            return roles
        page += 1


# The organization role GitHub calls an owner.
ORG_ADMIN_ROLE = "admin"


class AccountAuthority:
    """The GitHub accounts one user administers, resolved once per flow.

    This is the entitlement a connection actually needs. A connection is not
    repository-shaped — it holds an installation, mints installation-wide
    tokens, and lists the installation's own repository set in Add Project — so
    the question is not "which repositories can you reach today" but "do you
    administer the account this installation sits on". That is GitHub's own gate
    on installing and uninstalling the App, and it does not decay: an owner is
    entitled to whatever their installation covers next week, while a snapshot
    of repository reach is undone the moment a repository is added to the
    installation.

    Two answers settle it and both are free of App permissions: ``GET /user``
    names the user, whose own account is theirs by definition, and
    ``GET /user/memberships/orgs`` gives their role in every organization.
    Fetched lazily and kept, so a picker holding ten candidates asks GitHub at
    most twice — and only the question the candidates actually raise.
    """

    def __init__(self, user_token: str):
        self._user_token = user_token
        self._user: dict | None = None
        self._org_roles: dict[str, str] | None = None

    @property
    def user(self) -> dict:
        if self._user is None:
            self._user = get_authenticated_user(self._user_token)
        return self._user

    @property
    def user_id(self):
        return self.user.get("id")

    @property
    def admin_orgs(self) -> set[str]:
        """Lowered logins of the organizations this user owns."""
        if self._org_roles is None:
            self._org_roles = list_user_org_roles(self._user_token)
        return {
            login
            for login, role in self._org_roles.items()
            if role == ORG_ADMIN_ROLE
        }

    def administers(
        self, account_type: str, account_login: str, account_id=None
    ) -> bool:
        """Whether this user administers one installation's account.

        Anything GitHub might invent later — an enterprise-level install, a new
        account type — falls through to ``False``: an account shape we cannot
        reason about is one we must not hand over.
        """
        if account_type == "User":
            if account_id is not None and self.user_id is not None:
                # Compared as text: both are integers from GitHub, and a
                # comparison that cannot raise keeps a malformed id a refusal
                # rather than a 500 in the middle of someone's install.
                return str(account_id) == str(self.user_id)
            # No id to compare: logins are unique, so they will do.
            login = (account_login or "").lower()
            return bool(login) and login == (self.user.get("login") or "").lower()
        if account_type == "Organization":
            login = (account_login or "").lower()
            return bool(login) and login in self.admin_orgs
        return False


def user_administers_installation(
    user_token: str, installation_id: int, authority: AccountAuthority | None = None
) -> bool:
    """Whether this user administers the account behind an installation id.

    A callback hands us an id and nothing else, so the account comes from the
    App's own view of the installation. Reading it discloses nothing: the
    caller learns only the verdict, which is the same refusal whether the
    installation is someone else's or absent entirely.

    Raises on a GitHub error rather than guessing, so callers fail closed.
    """
    installation = get_installation(installation_id)
    account = installation.get("account") or {}
    authority = authority or AccountAuthority(user_token)
    return authority.administers(
        account.get("type", ""), account.get("login", ""), account.get("id")
    )
