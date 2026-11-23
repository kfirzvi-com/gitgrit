"""Adding the projects the analysis suggested from inside a repository.

A whole-repository project's dependency analysis lists the apps, services
and libraries its repository holds (``Project.suggested_projects``). Adding
one makes it a project of its own, rooted at its directory, set up exactly
like one added by hand (``project_management.add_project``): same
connection and repository, the suggestion's name, kind, description and tech
labels, and the stacks it was in before it was a project.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application import project_management, stack_service
from app.domain.models import Project, Stack


@dataclass(frozen=True)
class AddedSuggestions:
    added: tuple  # the new projects
    already: int  # paths that were projects already


class ProjectSuggestions:
    def __init__(self, project: Project, user=None):
        self.project = project
        self.user = user

    def add(self, paths) -> AddedSuggestions:
        """Add the open suggestions at ``paths`` (all of them when None)."""
        open_ = {s.path: s for s in self.project.open_suggestions()}
        wanted = list(open_) if paths is None else [p for p in paths if p]
        added, already = [], 0
        for path in wanted:
            suggestion = open_.get(path)
            if suggestion is None:
                already += 1
                continue
            try:
                result = project_management.add_project(
                    self.project.tenant,
                    self.user,
                    self.project.platform_connection,
                    self._repository(suggestion),
                    root_path=suggestion.path,
                    lifecycle=self.project.lifecycle,
                    owner=self.project.owner,
                )
            except project_management.AlreadyAdded:
                already += 1
                continue
            new = result.project
            new.kind = suggestion.kind
            new.technologies = list(suggestion.technologies)
            new.save(update_fields=["kind", "technologies"])
            if suggestion.stack_ids:
                stack_service.add_project_to_stacks(
                    tenant=self.project.tenant,
                    project=new,
                    stacks=Stack.objects.filter(tenant=self.project.tenant, pk__in=suggestion.stack_ids),
                )
            added.append(new)
        return AddedSuggestions(added=tuple(added), already=already)

    def _repository(self, suggestion) -> dict:
        """The repository as ``add_project`` takes it, named for the suggestion."""
        p = self.project
        return {
            "external_id": p.external_id,
            "name": p.name,
            "full_path": p.full_path,
            "web_url": p.web_url,
            "default_branch": p.default_branch,
            "description": suggestion.description,
        }
