import asyncio

from app.infrastructure.mcp.auth import MCPBearerAuth
from app.infrastructure.mcp.context import reset_auth, set_auth


async def _send_401(send) -> None:
    await send({"type": "http.response.start", "status": 401, "headers": []})
    await send({"type": "http.response.body", "body": b"Unauthorized"})


class MCPAuthMiddleware:
    def __init__(self, app):
        self.app = app
        self._auth = MCPBearerAuth()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth_header = headers.get(b"authorization", b"").decode()

        if not auth_header.startswith("Bearer "):
            await _send_401(send)
            return

        raw_token = auth_header[7:]
        loop = asyncio.get_running_loop()
        try:
            auth_context = await loop.run_in_executor(None, self._auth.resolve, raw_token)
        except PermissionError:
            await _send_401(send)
            return

        ctx_token = set_auth(auth_context.user, auth_context.tenant)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_auth(ctx_token)
