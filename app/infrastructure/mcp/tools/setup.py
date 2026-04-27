from app.infrastructure.mcp.context import get_auth
from app.infrastructure.mcp.registry import register
from app.infrastructure.mcp.setup.rule_files import render

_SUPPORTED_CLIENTS = ("cursor", "cline")
_NOT_APPLICABLE = {
    "error": "not_applicable",
    "message": (
        "export_setup_files is only available for generic-kind MCP tokens. "
        "Claude Code and Claude Desktop receive equivalent guidance via the "
        "GitGrit plugin's SessionStart hook. If you need a Cursor or Cline "
        "rule file, generate a generic-kind API token in the GitGrit profile "
        "page."
    ),
}


@register
async def export_setup_files(client: str = "all") -> dict:
    """Return editor rule-file content for non-Claude MCP clients.

    Type "set up GitGrit for this project" or call this tool directly to
    receive a rule file your editor will surface as a system prompt — that
    file primes the assistant to call ``session_bootstrap`` and
    ``validate_edit`` even when the editor doesn't surface MCP server
    instructions.

    Args:
        client: ``"cursor"``, ``"cline"``, or ``"all"`` (default).

    Returns:
        ``{"files": [{"path": "...", "content": "..."}]}`` for generic-kind
        tokens. Claude-kind tokens receive a structured "not applicable"
        response with a pointer to the GitGrit profile page.
    """
    auth = get_auth()
    if auth.client_kind != "generic":
        return _NOT_APPLICABLE

    if client == "all":
        return {
            "files": [
                {"path": path, "content": content}
                for path, content in (render(c) for c in _SUPPORTED_CLIENTS)
            ]
        }

    if client not in _SUPPORTED_CLIENTS:
        return {
            "error": "unsupported_client",
            "supported": list(_SUPPORTED_CLIENTS),
            "message": f"Unsupported client {client!r}; pass one of {_SUPPORTED_CLIENTS} or 'all'.",
        }

    path, content = render(client)  # type: ignore[arg-type]
    return {"files": [{"path": path, "content": content}]}
