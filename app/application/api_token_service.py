import hashlib

from django.utils import timezone

from app.domain.models import APIToken


def resolve_api_token(raw_token: str) -> APIToken:
    """Resolve a raw bearer token to its APIToken row.

    Shared by the MCP middleware and any HTTP endpoint that authenticates with
    the same `grit_` bearer scheme. Raises PermissionError on miss; updates
    last_used_at on hit. The returned instance has user and tenant pre-fetched.
    """
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    try:
        api_token = (
            APIToken.objects
            .select_related("user", "tenant")
            .get(token_hash=token_hash)
        )
    except APIToken.DoesNotExist:
        raise PermissionError("Invalid token")
    APIToken.objects.filter(pk=api_token.pk).update(last_used_at=timezone.now())
    return api_token
