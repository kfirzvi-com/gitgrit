from drf_spectacular.extensions import OpenApiAuthenticationExtension
from oauth2_provider.contrib.rest_framework import TokenHasReadWriteScope
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from app.application.api_token_service import resolve_api_token
from app.domain.models import APIToken


class APITokenAuthentication(BaseAuthentication):
    """``Authorization: Bearer grit_...`` — an :class:`APIToken`.

    ``request.auth`` is the token. A personal token's ``request.user`` is its
    owner; a workspace token has no user behind it, so ``request.user`` is
    anonymous and the workspace is the only thing it can reach. Any other
    bearer token is left to the OAuth authenticator.
    """

    def authenticate(self, request):
        header = get_authorization_header(request).decode()
        if not header.startswith("Bearer grit_"):
            return None
        try:
            api_token = resolve_api_token(header[7:].strip())
        except PermissionError:
            raise AuthenticationFailed("Invalid token.")
        return api_token.user or AnonymousUser(), api_token

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) when credentials are missing.
        return 'Bearer realm="api"'


class APITokenAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = APITokenAuthentication
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "description": (
                "A `grit_pat_` personal token (profile page; acts as you in all your "
                "workspaces) or a `grit_ws_` workspace token (workspace settings; "
                "reaches only that workspace, for CI/CD)."
            ),
        }


class HasToken(BasePermission):
    """Authenticated by a bearer token: OAuth, personal or workspace.

    Stands in for ``IsAuthenticated``, which a workspace token (no user)
    would fail. The API has no session authentication, so ``request.auth``
    is always a token here.
    """

    def has_permission(self, request, view):
        return request.auth is not None


class ReadWriteScope(TokenHasReadWriteScope):
    """OAuth tokens need ``read`` for safe methods and ``write`` otherwise.

    ``grit_`` tokens carry no scopes: they have their owner's full access.
    """

    def has_permission(self, request, view):
        if isinstance(request.auth, APIToken):
            return True
        return super().has_permission(request, view)
