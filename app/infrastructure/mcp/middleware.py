import asyncio

from django.db import close_old_connections

from app.infrastructure.mcp.auth import MCPBearerAuth
from app.infrastructure.mcp.context import reset_auth, set_auth


async def _send_401(send) -> None:
    await send({"type": "http.response.start", "status": 401, "headers": []})
    await send({"type": "http.response.body", "body": b"Unauthorized"})


class MCPAuthMiddleware:
    def __init__(self, app):
        self.app = app
        self._auth = MCPBearerAuth()

    def _resolve(self, raw_token):
        """Resolve the token in a thread-pool thread, managing the DB connection.

        Django ties connection hygiene to its request signals, which never fire
        for work handed to `run_in_executor`. Without this, the pool thread opens
        a connection on its first MCP request and then reuses it forever — so
        once that connection dies (idle timeout, DB restart, failover) every
        later request on the same thread raises
        `psycopg.OperationalError: the connection is closed` and the endpoint
        500s until the worker is replaced. Staging did exactly that after
        sitting idle for 13 days.

        `close_old_connections` is what Django itself runs on request start and
        finish: it drops connections that are unusable or past CONN_MAX_AGE.
        """
        close_old_connections()
        try:
            return self._auth.resolve(raw_token)
        finally:
            close_old_connections()

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
            auth_context = await loop.run_in_executor(None, self._resolve, raw_token)
        except PermissionError:
            await _send_401(send)
            return

        ctx_token = set_auth(auth_context)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_auth(ctx_token)
