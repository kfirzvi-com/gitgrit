from contextvars import ContextVar
from typing import Literal, NamedTuple

from app.domain.models import Tenant, User

ClientKind = Literal["claude", "generic"]


class AuthContext(NamedTuple):
    user: User
    tenant: Tenant
    client_kind: ClientKind


_auth_var: ContextVar[AuthContext | None] = ContextVar("mcp_auth", default=None)


def set_auth(auth: AuthContext) -> object:
    return _auth_var.set(auth)


def reset_auth(token: object) -> None:
    _auth_var.reset(token)


def get_auth() -> AuthContext:
    ctx = _auth_var.get()
    if ctx is None:
        raise RuntimeError("MCP auth context is not set")
    return ctx
