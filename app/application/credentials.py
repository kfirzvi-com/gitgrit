"""The credentials a project's jobs hold, for keeping them out of logs and
stored errors (see ``app.infrastructure.redaction``)."""
from __future__ import annotations

import logging

from app.application.standard_engine import resolve_llm_roles
from app.infrastructure import github_app
from app.infrastructure.redaction import secrets_of

logger = logging.getLogger(__name__)


def project_secrets(project) -> set[str]:
    """The stored repository token, the workspace's LLM keys (the roles
    ``dependency_agent`` and the sandbox input resolve) and the GitHub App
    installation tokens minted for the project's connection in this process
    (minted per job, stored nowhere).

    Never raises: it runs on failure paths and must not hide the original
    error. A part that can't be read is skipped, the rest is kept."""
    tokens: list = []
    llm_roles = None
    connection = None
    try:
        connection = project.platform_connection
        tokens.append(getattr(connection, "access_token", None))
    except Exception:  # noqa: BLE001
        logger.warning("could not read the token to redact for project %s", project.pk)
    try:
        llm_roles = resolve_llm_roles(project.tenant)
    except Exception:  # noqa: BLE001
        logger.warning("could not read the LLM keys to redact for project %s", project.pk)
    installation_id = getattr(connection, "installation_id", None)
    if installation_id:
        try:
            tokens.extend(github_app.cached_tokens(installation_id))
        except Exception:  # noqa: BLE001
            logger.warning("could not read minted tokens to redact for project %s", project.pk)
    return secrets_of(*tokens, llm_roles=llm_roles)
