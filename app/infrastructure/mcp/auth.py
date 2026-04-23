import hashlib

from django.utils import timezone

from app.domain.models import APIToken
from app.infrastructure.mcp.context import AuthContext


class MCPBearerAuth:
    def resolve(self, raw_token: str) -> AuthContext:
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
        return AuthContext(user=api_token.user, tenant=api_token.tenant)
