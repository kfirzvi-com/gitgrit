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
        mock_resolve.return_value = AuthContext(user=user, tenant=tenant)

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
        mock_resolve.return_value = AuthContext(user=user, tenant=tenant)

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
