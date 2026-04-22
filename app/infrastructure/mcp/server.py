from mcp.server.fastmcp import FastMCP

from app.infrastructure.mcp import tools as _tools_module  # noqa: F401 — populates registry
from app.infrastructure.mcp.instructions import build_instructions
from app.infrastructure.mcp.middleware import MCPAuthMiddleware
from app.infrastructure.mcp.registry import apply_all, apply_all_prompts

mcp = FastMCP("GitGrit", instructions=build_instructions())
apply_all(mcp)
apply_all_prompts(mcp)

mcp_app = MCPAuthMiddleware(mcp.streamable_http_app())
