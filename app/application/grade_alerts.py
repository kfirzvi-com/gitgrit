"""Telling people about the grade where they already look.

Once a workspace is set up, GitGrit only exists when someone opens it. The
project page already computes an overall score, a grade and the worst
standards (``ProjectStatusService``); this module delivers that to the commit
in GitHub after every run, as a ``gitgrit/grade`` commit status on the PR
checks list and next to the commit. A webhook run posts to the event's commit;
a run with no commit of its own (Run / Run All, attach, save, activate, and
events like a release) posts to the head of the project's default branch.

Called from the end of the ``run_standards`` job (``app.tasks``), never from
a request. Nothing here may fail the run: a refused write (the GitHub App
permission not yet accepted, a PAT without the scope) or a platform outage is
logged and skipped.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.urls import reverse

from app.application.project_status_service import ProjectStatusService
from app.domain.models import Project
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger(__name__)

# Grade bucket -> commit status state. GitHub also knows "error" and
# "pending"; a grade is only ever a pass or a fail.
GRADE_STATE = {
    "excellent": "success",
    "good": "success",
    "warning": "failure",
    "critical": "failure",
}


def grade_status_line(status: dict) -> tuple[str, str]:
    """The commit status ``(state, description)`` for a project status dict.

    ``Grade warning · 62/100 · 5/9 passed · worst: secrets-in-repo`` — the
    "worst" is the lowest-scoring standard, named only when something failed.
    Raises ``KeyError`` for an ``unknown`` grade: callers skip those.
    """
    grade = status["grade"]
    state = GRADE_STATE[grade]
    score = round(status["overall_score"] or 0)
    parts = [
        f"Grade {grade}",
        f"{score}/100",
        f"{status['passed']}/{status['total_standards']} passed",
    ]
    if status["failed"] and status["top_offenders"]:
        parts.append(f"worst: {status['top_offenders'][0]['name']}")
    return state, " · ".join(parts)


def project_url(project: Project) -> str:
    return settings.SITE_URL.rstrip("/") + reverse("project_detail", args=[project.pk])


def report_commit_status(project: Project, commit_sha: str | None = None) -> None:
    """Post the project's current grade as a commit status on its platform.

    ``commit_sha`` is the commit the run was about; ``None`` means the run had
    none, and the status goes to the head of the project's default branch
    (looked up on the platform). Posts nothing while the grade is ``unknown``
    (no results yet) or when the head cannot be resolved. Never raises: the
    run already succeeded, and a status is a courtesy.
    """
    try:
        status = ProjectStatusService().get_project_status(project.tenant, project.id)
        if status["grade"] == "unknown":
            return
        state, description = grade_status_line(status)
        client = get_platform_client(project.platform_connection)
        if not commit_sha:
            commit_sha = client.get_branch_head(project.full_path, project.default_branch)
            if not commit_sha:
                logger.info(
                    "no head for %s@%s; skipping commit status",
                    project.full_path,
                    project.default_branch,
                )
                return
        client.set_commit_status(
            project.full_path, commit_sha, state, description, project_url(project)
        )
    except Exception:
        logger.warning(
            "could not post commit status for project %s at %s",
            project.pk,
            commit_sha,
            exc_info=True,
        )
