import asyncio
from unittest.mock import MagicMock, patch

from django.test import TestCase
from starlette.testclient import TestClient

from app.infrastructure.mcp.auth import MCPBearerAuth
from app.infrastructure.mcp.context import AuthContext, get_auth
from app.infrastructure.mcp.middleware import MCPAuthMiddleware


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class TestMCPAuthMiddleware(TestCase):
    def test_missing_authorization_header_returns_401(self):
        client = TestClient(MCPAuthMiddleware(_ok_app), raise_server_exceptions=True)
        response = client.get("/")
        assert response.status_code == 401
        assert response.content == b"Unauthorized"

    def test_non_bearer_scheme_returns_401(self):
        client = TestClient(MCPAuthMiddleware(_ok_app), raise_server_exceptions=True)
        response = client.get("/", headers={"Authorization": "Basic abc123"})
        assert response.status_code == 401

    @patch.object(MCPBearerAuth, "resolve", side_effect=PermissionError("Invalid token"))
    def test_invalid_token_returns_401(self, mock_resolve):
        client = TestClient(MCPAuthMiddleware(_ok_app), raise_server_exceptions=True)
        response = client.get("/", headers={"Authorization": "Bearer bad_token"})
        assert response.status_code == 401
        mock_resolve.assert_called_once_with("bad_token")

    @patch.object(MCPBearerAuth, "resolve")
    def test_valid_token_reaches_inner_app(self, mock_resolve):
        user = MagicMock()
        tenant = MagicMock()
        mock_resolve.return_value = AuthContext(user=user, tenant=tenant, client_kind="claude")

        reached = []

        async def stub(scope, receive, send):
            reached.append(True)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        client = TestClient(MCPAuthMiddleware(stub), raise_server_exceptions=True)
        response = client.get("/", headers={"Authorization": "Bearer grit_valid"})
        assert response.status_code == 200
        assert reached == [True]

    @patch.object(MCPBearerAuth, "resolve")
    def test_auth_context_set_during_inner_app_call(self, mock_resolve):
        user = MagicMock()
        tenant = MagicMock()
        mock_resolve.return_value = AuthContext(user=user, tenant=tenant, client_kind="claude")

        captured = []

        async def capturing_app(scope, receive, send):
            captured.append(get_auth())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        client = TestClient(MCPAuthMiddleware(capturing_app), raise_server_exceptions=True)
        client.get("/", headers={"Authorization": "Bearer grit_valid"})

        assert len(captured) == 1
        assert captured[0].user is user
        assert captured[0].tenant is tenant

    def test_lifespan_scope_bypasses_auth(self):
        reached = []

        async def stub(scope, receive, send):
            reached.append(scope["type"])

        middleware = MCPAuthMiddleware(stub)
        scope = {"type": "lifespan", "headers": []}

        async def run():
            await middleware(scope, None, None)

        asyncio.run(run())
        assert reached == ["lifespan"]


class TestDatabaseConnectionHygiene(TestCase):
    """Token resolution runs in a thread pool, where Django manages nothing.

    Django's connection hygiene is driven by its request_started/request_finished
    signals, which never fire for `run_in_executor` work. Left alone, a pool
    thread reuses one connection forever; when that connection dies (idle
    timeout, DB restart, failover) every later request on the thread raises
    `psycopg.OperationalError: the connection is closed`, 500ing the endpoint
    until the worker is replaced. Staging did exactly that after 13 idle days.
    """

    def _auth_context(self):
        return AuthContext(user=MagicMock(), tenant=MagicMock(), client_kind="claude")

    @patch("app.infrastructure.mcp.middleware.close_old_connections")
    @patch.object(MCPBearerAuth, "resolve")
    def test_stale_connections_are_dropped_around_resolution(self, mock_resolve, mock_close):
        mock_resolve.return_value = self._auth_context()
        client = TestClient(MCPAuthMiddleware(_ok_app), raise_server_exceptions=True)

        response = client.get("/", headers={"Authorization": "Bearer grit_valid"})

        assert response.status_code == 200
        # Before, so a connection that died since the last request is discarded
        # rather than reused; after, so this request leaves nothing behind.
        assert mock_close.call_count == 2

    @patch("app.infrastructure.mcp.middleware.close_old_connections")
    @patch.object(MCPBearerAuth, "resolve", side_effect=PermissionError("Invalid token"))
    def test_connections_are_released_even_when_the_token_is_rejected(
        self, mock_resolve, mock_close
    ):
        # The rejection path is the common one for a scanner or a stale client;
        # it must not strand a connection in the pool thread either.
        client = TestClient(MCPAuthMiddleware(_ok_app), raise_server_exceptions=True)

        response = client.get("/", headers={"Authorization": "Bearer grit_bogus"})

        assert response.status_code == 401
        assert mock_close.call_count == 2
