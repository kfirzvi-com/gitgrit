from django.conf import settings as django_settings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.infrastructure.mcp import tools as _tools_module  # noqa: F401 — populates registry
from app.infrastructure.mcp.context import get_auth
from app.infrastructure.mcp.instructions import build_instructions, select_instructions
from app.infrastructure.mcp.middleware import MCPAuthMiddleware
from app.infrastructure.mcp.registry import apply_all, apply_all_prompts

# MCP's StreamableHTTP transport ships DNS-rebinding protection that defaults
# to rejecting every Host header unless an allow-list is supplied. Mirror
# Django's ALLOWED_HOSTS so the public hostname (driven by SITE_URL) is
# accepted in each environment. The check matches the *full* Host header
# including any explicit port, so we also add a `host:*` wildcard per entry —
# harmless in production (served on 80/443 with no explicit port) but required
# for local ASGI dev on a non-standard port (e.g. 127.0.0.1:8000).
#
# `stateless_http=True` is required because we run under gunicorn with multiple
# workers. In the default stateful mode the session table created by
# `initialize` lives in one worker's memory, so any follow-up request that the
# OS hands to a sibling worker gets `404 -32600 "Session not found"`. Clients
# fire tools/list, prompts/list and resources/list concurrently right after
# initialize, so at least one reliably lands on the wrong worker; the client
# reads that as an expired session, tears the transport down, and retries into
# the same race — surfacing as "Failed to fetch tools: Not connected".
# Stateless mode makes every request self-contained. We use no server-initiated
# features (progress, sampling, elicitation, subscriptions), so nothing is lost.
_allowed_hosts = list(django_settings.ALLOWED_HOSTS)
_allowed_hosts += [f"{host}:*" for host in django_settings.ALLOWED_HOSTS]
mcp = FastMCP(
    "GitGrit",
    instructions=build_instructions(),
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
    ),
)
apply_all(mcp)
apply_all_prompts(mcp)


# FastMCP's underlying lowlevel.Server captures `instructions` once per session creation
# inside `create_initialization_options()`. We wrap that method on the instance so the
# right flavor is chosen at session-creation time based on the bound client kind. The
# auth context var is set by MCPAuthMiddleware before this runs.
_original_create_io = mcp._mcp_server.create_initialization_options


def _create_initialization_options(*args, **kwargs):
    options = _original_create_io(*args, **kwargs)
    try:
        client_kind = get_auth().client_kind
    except RuntimeError:
        client_kind = "claude"
    options.instructions = select_instructions(client_kind)
    return options


mcp._mcp_server.create_initialization_options = _create_initialization_options

mcp_app = MCPAuthMiddleware(mcp.streamable_http_app())
