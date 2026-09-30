"""Shared argument handling for commands that take a project id."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.management.base import CommandError

from app.domain.models import Project


def project_or_command_error(project_id) -> Project:
    """The project with this id, or a ``CommandError`` — also for an id that
    is not a UUID at all, which the ORM would otherwise turn into a traceback."""
    project_id = str(project_id)
    try:
        project = Project.objects.filter(pk=project_id).first()
    except (ValidationError, ValueError):
        project = None
    if project is None:
        raise CommandError(f"No such project: {project_id}")
    return project
