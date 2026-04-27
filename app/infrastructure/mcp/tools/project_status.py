from asgiref.sync import sync_to_async

from app.application.policy_service import PolicyService
from app.application.project_service import ProjectService
from app.application.project_status_service import ProjectStatusService
from app.infrastructure.mcp.context import get_auth
from app.infrastructure.mcp.registry import register

_project_service = ProjectService()
_status_service = ProjectStatusService()
_policy_service = PolicyService()


@register
async def resolve_project(
    repo_full_path: str | None = None, web_url: str | None = None
) -> dict:
    """Resolve a local git repo to a GitGrit project by full_path or web_url.

    Pass ``repo_full_path`` (e.g. ``"acme/backend"``) and/or ``web_url``. On a
    miss, returns ``{"error": "no_match", "candidates": [...]}`` with up to 5
    close matches.

    Deprecated for plugin use; prefer ``session_bootstrap`` for SessionStart,
    which fans out project + status + policies in a single round-trip. Retained
    for external MCP clients.
    """
    tenant = get_auth().tenant
    return await sync_to_async(_project_service.resolve_project)(
        tenant, repo_full_path, web_url
    )


@register
async def get_project_status(project_id: str) -> dict:
    """Return overall compliance grade and top offending policies for a project.

    If you don't have a project_id yet, call ``session_bootstrap`` first with the
    git remote URL or the org/repo path.

    Aggregates the latest execution per policy.

    Deprecated for plugin use; prefer ``session_bootstrap`` for SessionStart.
    Retained for external MCP clients.
    """
    tenant = get_auth().tenant
    return await sync_to_async(_status_service.get_project_status)(tenant, project_id)


@register
async def get_active_policies_for_project(project_id: str) -> list[dict]:
    """Return all active, non-draft policies applicable to a project.

    If you don't have a project_id yet, call ``session_bootstrap`` first with the
    git remote URL or the org/repo path.

    Each policy carries a ``rules`` block (watched files, kind-tagged forbidden
    patterns, and local-enforceability / completeness flags) produced by the
    server-side extractor; raw ``code`` is not shipped. Only language-match is
    applied — events and ref patterns are webhook-time filters and are omitted
    here.

    Deprecated for plugin use; prefer ``session_bootstrap`` for SessionStart.
    Retained for external MCP clients.
    """
    tenant = get_auth().tenant
    return await sync_to_async(_policy_service.list_active_for_project)(
        tenant, project_id
    )


@register
async def session_bootstrap(
    repo_full_path: str | None = None, web_url: str | None = None
) -> dict:
    """One-shot SessionStart bootstrap: project + status + active policies.

    Fans out the work previously done by three sequential tool calls
    (``resolve_project`` → ``get_project_status`` → ``get_active_policies_for_project``)
    into a single round-trip. Call at session start to map the developer's
    working directory to a GitGrit project and load enforcement rules.

    Always returns the same three keys. On project resolution failure the
    ``project`` entry carries ``{"error": "no_match", "candidates": [...]}`` and
    both ``status`` and ``policies`` are ``None`` — callers should branch on
    ``"error" in project``, not on key presence.
    """
    tenant = get_auth().tenant
    project = await sync_to_async(_project_service.resolve_project)(
        tenant, repo_full_path, web_url
    )
    if "error" in project:
        return {"project": project, "status": None, "policies": None}
    status = await sync_to_async(_status_service.get_project_status)(
        tenant, project["id"]
    )
    policies = await sync_to_async(_policy_service.list_active_for_project)(
        tenant, project["id"]
    )
    return {"project": project, "status": status, "policies": policies}
