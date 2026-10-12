import hashlib

from django.utils import timezone

from app.domain.models import APIToken


def resolve_api_token(raw_token: str) -> APIToken:
    """Resolve a raw ``grit_`` bearer token to its APIToken row.

    Raises PermissionError on a miss, or when a personal token's user has been
    deactivated; updates last_used_at on a hit. The returned instance has user
    and tenant pre-fetched.
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
    if api_token.user is not None and not api_token.user.is_active:
        raise PermissionError("Invalid token")
    APIToken.objects.filter(pk=api_token.pk).update(last_used_at=timezone.now())
    return api_token
