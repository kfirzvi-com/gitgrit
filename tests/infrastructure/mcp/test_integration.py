"""End-to-end integration tests for the MCP HTTP stack.

TestMCPHTTPAuth validates the auth layer through the full ASGI application
without needing to speak the MCP wire protocol.

TestTenancyIsolation validates that tool functions enforce tenant boundaries
against a real database (no service-layer mocking).
"""
import asyncio
import hashlib

from django.db import connections
from django.test import TestCase, TransactionTestCase
from model_bakery import baker
from starlette.testclient import TestClient

from app.infrastructure.mcp import context
from app.infrastructure.mcp.tools.standards import list_standards
from gitgrit.asgi import application


class TestMCPHTTPAuth(TestCase):
    """HTTP-level authentication tests against the full ASGI stack."""

    def tearDown(self):
        connections.close_all()
        super().tearDown()

    def test_no_auth_header_returns_401(self):
        client = TestClient(application, raise_server_exceptions=False)
        resp = client.post("/mcp/")
        self.assertEqual(resp.status_code, 401)

    def test_wrong_auth_scheme_returns_401(self):
        client = TestClient(application, raise_server_exceptions=False)
        resp = client.post("/mcp/", headers={"Authorization": "Basic abc123"})
        self.assertEqual(resp.status_code, 401)

    def test_bearer_keyword_only_returns_401(self):
        # "Bearer" without the trailing space fails the startswith check
        client = TestClient(application, raise_server_exceptions=False)
        resp = client.post("/mcp/", headers={"Authorization": "Bearer"})
        self.assertEqual(resp.status_code, 401)

    def test_unknown_token_returns_401(self):
        client = TestClient(application, raise_server_exceptions=False)
        resp = client.post("/mcp/", headers={"Authorization": "Bearer grit_nosuchtoken"})
        self.assertEqual(resp.status_code, 401)

    def test_health_check_still_returns_200(self):
        # Verify the Django path works through _PathDispatcher even with MCP mounted
        client = TestClient(application, raise_server_exceptions=False)
        resp = client.get("/up/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "OK")

    def test_transport_security_allows_site_hostname(self):
        # MCP's TransportSecurityMiddleware defaults to rejecting every Host
        # header. Without explicit allowed_hosts, every prod request gets a
        # 421 "Invalid Host header". Pin that the SITE_URL hostname plus the
        # localhost defaults are in the allow-list.
        from urllib.parse import urlparse

        from django.conf import settings as django_settings

        from app.infrastructure.mcp.server import mcp

        security = mcp.settings.transport_security
        self.assertIsNotNone(security)
        self.assertTrue(security.enable_dns_rebinding_protection)
        self.assertIn("localhost", security.allowed_hosts)
        self.assertIn("127.0.0.1", security.allowed_hosts)
        site_host = urlparse(django_settings.SITE_URL).hostname
        if site_host:
            self.assertIn(site_host, security.allowed_hosts)


class TestTenancyIsolation(TransactionTestCase):
    """Verify that MCP tools enforce tenant boundaries against the real database.

    TransactionTestCase (not TestCase) is required because list_standards uses
    sync_to_async, which runs the ORM in a thread-pool executor with its own DB
    connection. TestCase wraps tests in a transaction that is invisible to other
    connections; TransactionTestCase commits data to the real DB so cross-thread
    queries see it.
    """

    def tearDown(self):
        connections.close_all()
        super().tearDown()

    def setUp(self):
        self.user_a = baker.make("app.User")
        self.tenant_a = baker.make("app.Tenant")
        self.user_b = baker.make("app.User")
        self.tenant_b = baker.make("app.Tenant")
        self.standard_a = baker.make(
            "app.Standard", tenant=self.tenant_a, name="Tenant A Standard"
        )

    def test_tenant_b_cannot_see_tenant_a_standards(self):
        ctx_token = context.set_auth(
            context.AuthContext(user=self.user_b, tenant=self.tenant_b, client_kind="claude")
        )
        try:
            result = asyncio.run(list_standards())
        finally:
            context.reset_auth(ctx_token)
        returned_ids = {p["id"] for p in result}
        self.assertNotIn(str(self.standard_a.id), returned_ids)

    def test_tenant_a_sees_its_own_standards(self):
        ctx_token = context.set_auth(
            context.AuthContext(user=self.user_a, tenant=self.tenant_a, client_kind="claude")
        )
        try:
            result = asyncio.run(list_standards())
        finally:
            context.reset_auth(ctx_token)
        returned_ids = {p["id"] for p in result}
        self.assertIn(str(self.standard_a.id), returned_ids)


class TestStatelessTransport(TransactionTestCase):
    """Pin the transport as stateless so multi-worker deploys keep working.

    Under gunicorn with `--workers 2` the stateful StreamableHTTP session table
    lives in a single worker's memory. A client that initializes on worker A and
    then has a follow-up request routed to worker B gets
    `404 -32600 "Session not found"`, treats it as an expired session, and drops
    the connection — "Failed to fetch tools: Not connected". A sibling worker
    sees exactly what this test sends: a request carrying no session ID.

    TransactionTestCase because the auth middleware resolves the token in a
    thread-pool executor with its own DB connection.
    """

    def tearDown(self):
        connections.close_all()
        super().tearDown()

    def setUp(self):
        self.raw_token = "grit_stateless_probe_token"
        baker.make(
            "app.APIToken",
            token_hash=hashlib.sha256(self.raw_token.encode()).hexdigest(),
            client_kind="claude",
        )
        self.headers = {
            "Authorization": f"Bearer {self.raw_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    def test_stateless_http_is_enabled(self):
        from app.infrastructure.mcp.server import mcp

        self.assertTrue(
            mcp.settings.stateless_http,
            "stateless_http must stay on — stateful sessions break under "
            "gunicorn's multiple workers (see class docstring)",
        )

    def test_requests_without_a_session_id_are_served(self):
        """A sibling worker's view: no mcp-session-id, and none handed back.

        Both requests share one `with` block because the session manager's task
        group is created by ASGI lifespan startup and may only be run once per
        instance — and `mcp_app` is a module-level singleton.
        """
        # base_url pins the Host header to an allowed host — TestClient's
        # default "testserver" is rejected by DNS-rebinding protection (421).
        with TestClient(
            application, base_url="http://localhost", raise_server_exceptions=False
        ) as client:
            init = client.post(
                "/mcp/",
                headers=self.headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            # Stateful mode rejects a bare tools/list outright ("Missing session
            # ID"); stateless mode must serve it.
            tools = client.post(
                "/mcp/",
                headers=self.headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            )

        self.assertEqual(init.status_code, 200)
        self.assertNotIn(
            "mcp-session-id",
            {k.lower() for k in init.headers},
            "no session may be issued — clients must not pin themselves to a worker",
        )
        self.assertEqual(tools.status_code, 200)
        self.assertIn("validate_edit", tools.text)
