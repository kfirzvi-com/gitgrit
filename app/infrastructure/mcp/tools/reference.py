from app.application.project_service import ProjectService
from app.infrastructure.mcp.registry import register

_service = ProjectService()


@register
def get_project_context_api() -> str:
    """Return the full API reference for the project object in evaluate(project).

    Call this before writing any policy code to understand exactly which
    methods are available, their return types, and see examples.
    """
    return _service.get_project_context_api()
