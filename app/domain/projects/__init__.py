"""Project domain: where a project lives inside its repository, what it is,
and the projects suggested from inside a monorepo."""
from app.domain.projects.project_kind import ProjectKind
from app.domain.projects.root_path import InvalidRootPath, RootPath
from app.domain.projects.suggested_project import SuggestedProject

__all__ = ["InvalidRootPath", "ProjectKind", "RootPath", "SuggestedProject"]
