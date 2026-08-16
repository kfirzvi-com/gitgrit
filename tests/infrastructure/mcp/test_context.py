from unittest.mock import MagicMock

from django.test import SimpleTestCase

from app.infrastructure.mcp.context import AuthContext, get_auth, reset_auth, set_auth


def _ctx(user, tenant, kind="claude"):
    return AuthContext(user=user, tenant=tenant, client_kind=kind)


class AuthContextTests(SimpleTestCase):
    def test_auth_context_is_namedtuple(self):
        self.assertTrue(issubclass(AuthContext, tuple))
        self.assertEqual(AuthContext._fields, ("user", "tenant", "client_kind"))

    def test_get_auth_raises_when_not_set(self):
        with self.assertRaisesRegex(RuntimeError, "MCP auth context is not set"):
            get_auth()

    def test_set_and_get_returns_context(self):
        user = MagicMock()
        tenant = MagicMock()
        token = set_auth(_ctx(user, tenant, "generic"))
        try:
            ctx = get_auth()
            self.assertIs(ctx.user, user)
            self.assertIs(ctx.tenant, tenant)
            self.assertEqual(ctx.client_kind, "generic")
        finally:
            reset_auth(token)

    def test_reset_clears_context(self):
        user = MagicMock()
        tenant = MagicMock()
        token = set_auth(_ctx(user, tenant))
        reset_auth(token)
        with self.assertRaises(RuntimeError):
            get_auth()

    def test_overwrite_context_returns_new_values(self):
        user_a = MagicMock()
        tenant_a = MagicMock()
        user_b = MagicMock()
        tenant_b = MagicMock()
        token_a = set_auth(_ctx(user_a, tenant_a))
        token_b = set_auth(_ctx(user_b, tenant_b))
        try:
            ctx = get_auth()
            self.assertIs(ctx.user, user_b)
            self.assertIs(ctx.tenant, tenant_b)
        finally:
            reset_auth(token_b)
            reset_auth(token_a)
