"""
ASGI config for gitgrit project.

It exposes the ASGI callable as a module-level variable named ``application``.
The MCP server is mounted at /mcp/ alongside the main Django application.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gitgrit.settings")

from django.core.asgi import get_asgi_application  # noqa: E402

# django.setup() is called inside get_asgi_application() — all imports of
# Django models must come after this line.
django_app = get_asgi_application()

from app.infrastructure.mcp.server import mcp_app  # noqa: E402


class _PathDispatcher:
    """Route /mcp* to the MCP ASGI app, everything else to Django.

    Using a plain dispatcher (not Starlette Mount) so the path prefix is NOT
    stripped — FastMCP's Starlette app expects to receive the full /mcp path.

    Lifespan events go to the MCP app so FastMCP can initialize its task group.
    Django handles HTTP requests fine without receiving its own lifespan startup.
    """

    def __init__(self, mcp, django):
        self._mcp = mcp
        self._django = django

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._mcp(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/mcp" or path.startswith("/mcp/"):
            await self._mcp(scope, receive, send)
        else:
            await self._django(scope, receive, send)


application = _PathDispatcher(mcp_app, django_app)
