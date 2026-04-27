from app.application.api_token_service import resolve_api_token
from app.infrastructure.mcp.context import AuthContext


class MCPBearerAuth:
    def resolve(self, raw_token: str) -> AuthContext:
        api_token = resolve_api_token(raw_token)
        return AuthContext(
            user=api_token.user,
            tenant=api_token.tenant,
            client_kind=api_token.client_kind,
        )
