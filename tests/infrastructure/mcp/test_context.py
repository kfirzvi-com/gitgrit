import pytest
from unittest.mock import MagicMock

from app.infrastructure.mcp.context import AuthContext, get_auth, reset_auth, set_auth


def _ctx(user, tenant, kind="claude"):
    return AuthContext(user=user, tenant=tenant, client_kind=kind)


def test_auth_context_is_namedtuple():
    assert issubclass(AuthContext, tuple)
    assert AuthContext._fields == ("user", "tenant", "client_kind")


def test_get_auth_raises_when_not_set():
    with pytest.raises(RuntimeError, match="MCP auth context is not set"):
        get_auth()


def test_set_and_get_returns_context():
    user = MagicMock()
    tenant = MagicMock()
    token = set_auth(_ctx(user, tenant, "generic"))
    try:
        ctx = get_auth()
        assert ctx.user is user
        assert ctx.tenant is tenant
        assert ctx.client_kind == "generic"
    finally:
        reset_auth(token)


def test_reset_clears_context():
    user = MagicMock()
    tenant = MagicMock()
    token = set_auth(_ctx(user, tenant))
    reset_auth(token)
    with pytest.raises(RuntimeError):
        get_auth()


def test_overwrite_context_returns_new_values():
    user_a = MagicMock()
    tenant_a = MagicMock()
    user_b = MagicMock()
    tenant_b = MagicMock()
    token_a = set_auth(_ctx(user_a, tenant_a))
    token_b = set_auth(_ctx(user_b, tenant_b))
    try:
        ctx = get_auth()
        assert ctx.user is user_b
        assert ctx.tenant is tenant_b
    finally:
        reset_auth(token_b)
        reset_auth(token_a)
