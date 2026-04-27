from pathlib import Path

from asgiref.sync import sync_to_async

from app.application.policy_service import PolicyService
from app.infrastructure.mcp.context import get_auth
from app.infrastructure.mcp.registry import register

_service = PolicyService()


@register
async def list_policies() -> list[dict]:
    """List all policies in the current workspace."""
    tenant = get_auth().tenant
    return await sync_to_async(_service.list_policies)(tenant)


@register
async def get_policy(policy_id: str) -> dict:
    """Get full details of a policy, including its Python code and recent executions."""
    tenant = get_auth().tenant
    return await sync_to_async(_service.get_policy)(tenant, policy_id)


@register
async def create_policy(
    name: str,
    code: str,
    description: str = "",
    events: list[str] | None = None,
    ref_pattern: str = "",
    languages: list[str] | None = None,
    labels: list[str] | None = None,
    draft: bool = False,
) -> dict:
    """Create a new GitGrit policy.

    The code must define an evaluate(project) function that returns
    {passed: bool, score: int (0-100), message: str, details: dict}.

    Use get_project_context_api() first to understand what methods are
    available on the project object.

    Args:
        name: Policy name.
        code: Python source code with an evaluate(project) function.
        description: Human-readable description of what the policy checks.
        events: Trigger events — any of ["push", "pull_request", "tag"].
        ref_pattern: Regex pattern for branch/ref filtering (e.g. "^main$").
        languages: Limit to projects using these languages (e.g. ["python"]).
        labels: Label names to assign (created if they don't exist).
        draft: If True, policy is saved but not executed on events.
    """
    auth = get_auth()
    user, tenant = auth.user, auth.tenant
    return await sync_to_async(_service.create_policy)(tenant, user, {
        "name": name,
        "code": code,
        "description": description,
        "events": events or [],
        "ref_pattern": ref_pattern,
        "languages": languages or [],
        "labels": labels or [],
        "draft": draft,
    })


@register
async def update_policy(
    policy_id: str,
    name: str | None = None,
    code: str | None = None,
    description: str | None = None,
    events: list[str] | None = None,
    ref_pattern: str | None = None,
    languages: list[str] | None = None,
    labels: list[str] | None = None,
    draft: bool | None = None,
    change_summary: str = "Updated via MCP",
) -> dict:
    """Update an existing policy. Only provided fields are changed.

    Creates a version snapshot so changes are tracked and reversible.
    """
    auth = get_auth()
    user, tenant = auth.user, auth.tenant
    data: dict = {"change_summary": change_summary}
    if name is not None:
        data["name"] = name
    if code is not None:
        data["code"] = code
    if description is not None:
        data["description"] = description
    if events is not None:
        data["events"] = events
    if ref_pattern is not None:
        data["ref_pattern"] = ref_pattern
    if languages is not None:
        data["languages"] = languages
    if labels is not None:
        data["labels"] = labels
    if draft is not None:
        data["draft"] = draft
    return await sync_to_async(_service.update_policy)(tenant, user, policy_id, data)


@register
async def delete_policy(policy_id: str) -> dict:
    """Permanently delete a policy."""
    tenant = get_auth().tenant
    await sync_to_async(_service.delete_policy)(tenant, policy_id)
    return {"deleted": True, "policy_id": policy_id}


@register
async def set_policy_code(
    policy_id: str,
    file_path: str,
    change_summary: str = "Code updated via file",
) -> dict:
    """Load policy code from a local file and save it to a policy.

    Use this instead of passing code inline to update_policy() when the policy
    contains regex patterns, backslashes, or other characters that may be
    distorted by string escaping. Writing code to a file first bypasses all
    escaping layers.

    Workflow:
        1. Write the policy code to a local file using the Write tool
           (e.g. /tmp/policy.py)
        2. Call this tool with the file path

    Args:
        policy_id: The policy to update.
        file_path: Absolute path to a local file containing the policy code.
        change_summary: Version history note.
    """
    auth = get_auth()
    user, tenant = auth.user, auth.tenant
    code = Path(file_path).read_text(encoding="utf-8")
    return await sync_to_async(_service.update_policy)(tenant, user, policy_id, {
        "code": code,
        "change_summary": change_summary,
    })
