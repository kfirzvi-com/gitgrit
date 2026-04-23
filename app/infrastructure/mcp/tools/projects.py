from asgiref.sync import sync_to_async

from app.application.project_service import ProjectService
from app.infrastructure.mcp.context import get_auth
from app.infrastructure.mcp.registry import register

_service = ProjectService()


@register
async def list_projects() -> list[dict]:
    """List all projects connected to the current workspace.

    Useful for understanding what languages and platforms are in use
    before writing targeted policies.
    """
    _, tenant = get_auth()
    return await sync_to_async(_service.list_projects)(tenant)
