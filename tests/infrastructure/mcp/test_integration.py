"""End-to-end integration tests for the MCP HTTP stack.

TestMCPHTTPAuth validates the auth layer through the full ASGI application
without needing to speak the MCP wire protocol.

TestTenancyIsolation validates that tool functions enforce tenant boundaries
against a real database (no service-layer mocking).
"""
import asyncio

from django.db import connections
from django.test import TestCase, TransactionTestCase
from model_bakery import baker
from starlette.testclient import TestClient

from app.infrastructure.mcp import context
from app.infrastructure.mcp.tools.policies import list_policies
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


class TestTenancyIsolation(TransactionTestCase):
    """Verify that MCP tools enforce tenant boundaries against the real database.

    TransactionTestCase (not TestCase) is required because list_policies uses
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
        self.policy_a = baker.make(
            "app.Policy", tenant=self.tenant_a, name="Tenant A Policy"
        )

    def test_tenant_b_cannot_see_tenant_a_policies(self):
        ctx_token = context.set_auth(
            context.AuthContext(user=self.user_b, tenant=self.tenant_b, client_kind="claude")
        )
        try:
            result = asyncio.run(list_policies())
        finally:
            context.reset_auth(ctx_token)
        returned_ids = {p["id"] for p in result}
        self.assertNotIn(str(self.policy_a.id), returned_ids)

    def test_tenant_a_sees_its_own_policies(self):
        ctx_token = context.set_auth(
            context.AuthContext(user=self.user_a, tenant=self.tenant_a, client_kind="claude")
        )
        try:
            result = asyncio.run(list_policies())
        finally:
            context.reset_auth(ctx_token)
        returned_ids = {p["id"] for p in result}
        self.assertIn(str(self.policy_a.id), returned_ids)
