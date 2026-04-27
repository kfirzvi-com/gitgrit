from asgiref.sync import sync_to_async

from app.application.edit_validator import EditValidator
from app.infrastructure.mcp.context import get_auth
from app.infrastructure.mcp.registry import register

_validator = EditValidator()


@register
async def validate_edit(
    project_id: str,
    file_path: str,
    new_content: str,
    prior_content: str | None = None,
) -> dict:
    """Check whether a proposed file edit introduces policy violations.

    Call this before every Edit/Write against a tracked file. If you don't
    have a project_id yet, call session_bootstrap first with the git remote
    URL or org/repo path.

    Pass the file's current content as ``prior_content`` (omit or pass null
    for new files) and the proposed content as ``new_content``. The server
    runs the project's active-policy forbidden_patterns engine against both
    versions and returns the diff:

    - ``introduced_violations`` — violations created by this edit. Block on
      these and propose a fix to the developer.
    - ``pre_existing_violations_count`` — violations already in the file
      before this edit. Reported for visibility; never blocks. Don't fix
      these unless the developer asks.
    - ``checked`` / ``skipped`` — policies evaluated vs. policies that don't
      apply to this file or aren't locally enforceable.
    - ``notes`` — soft warnings (e.g. extractor couldn't fully parse a rule;
      the sandbox will be authoritative on the next webhook event).
    """
    tenant = get_auth().tenant
    return await sync_to_async(_validator.validate_edit)(
        tenant, project_id, file_path, new_content, prior_content
    )
