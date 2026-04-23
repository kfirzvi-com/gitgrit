from contextvars import ContextVar
from typing import NamedTuple

from app.domain.models import Tenant, User


class AuthContext(NamedTuple):
    user: User
    tenant: Tenant


_auth_var: ContextVar[AuthContext | None] = ContextVar("mcp_auth", default=None)


def set_auth(user: User, tenant: Tenant) -> object:
    return _auth_var.set(AuthContext(user=user, tenant=tenant))


def reset_auth(token: object) -> None:
    _auth_var.reset(token)


def get_auth() -> AuthContext:
    ctx = _auth_var.get()
    if ctx is None:
        raise RuntimeError("MCP auth context is not set")
    return ctx
