from __future__ import annotations

from django.core.exceptions import ValidationError

from app.application import project_management, stack_service
from app.application.bulk_edit.bulk_edit_result import BulkEditResult
from app.application.errors import NotFoundError
from app.domain import importance
from app.domain.models import Project, Stack, Standard


class ProjectBulkEdit:
    """Changes many of a workspace's projects at once.

    A stack holds components, not projects: adding a project to a stack adds
    its root component; removing it takes out every one of its components.
    Attaching a standard queues it to run on each project, as attaching it
    to one does."""

    ACTIONS = (
        "set_owner", "set_lifecycle", "add_to_stack", "remove_from_stack", "attach_standard", "detach_standard",
    )

    def __init__(self, tenant, user):
        self.tenant = tenant
        self.user = user

    def projects(self, ids) -> list[Project]:
        try:
            return list(Project.objects.filter(tenant=self.tenant, pk__in=list(ids)).prefetch_related("components"))
        except (ValidationError, ValueError):
            raise NotFoundError("Unknown project.")

    def apply(self, action: str, ids, value: str = "", importance_value: str = "") -> BulkEditResult:
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown action {action!r}.")
        projects = self.projects(ids)
        if action == "attach_standard":
            return self.attach_standard(projects, value, importance_value)
        return getattr(self, action)(projects, value)

    def _result(self, done: str) -> BulkEditResult:
        return BulkEditResult(done=done, noun="project", noun_plural="projects")

    def set_owner(self, projects, owner: str) -> BulkEditResult:
        owner = (owner or "").strip()
        result = self._result(f'Set the owner to "{owner}" on' if owner else "Cleared the owner of")
        for project in projects:
            if project.owner == owner:
                result.unchanged += 1
                continue
            project_management.update_project(self.tenant, project.pk, owner=owner)
            result.changed += 1
        return result

    def set_lifecycle(self, projects, lifecycle: str) -> BulkEditResult:
        if lifecycle not in Project.Lifecycle.values:
            raise ValueError(f"Unknown lifecycle {lifecycle!r}.")
        result = self._result(f"Moved to {Project.Lifecycle(lifecycle).label}:")
        for project in projects:
            if project.lifecycle == lifecycle:
                result.unchanged += 1
                continue
            project_management.update_project(self.tenant, project.pk, lifecycle=lifecycle)
            result.changed += 1
        return result

    def add_to_stack(self, projects, stack_id: str) -> BulkEditResult:
        stack = self._stack(stack_id)
        result = self._result(f'Added to "{stack.name}":')
        for project in projects:
            root = next((c for c in project.components.all() if c.path == ""), None)
            if root is None:
                result.skip("no root component (add its components on the stack's page)")
                continue
            if stack_service.add_component_to_stack(tenant=self.tenant, stack=stack, component=root):
                result.changed += 1
            else:
                result.unchanged += 1
        return result

    def remove_from_stack(self, projects, stack_id: str) -> BulkEditResult:
        stack = self._stack(stack_id)
        result = self._result(f'Removed from "{stack.name}":')
        for project in projects:
            removed = [
                stack_service.remove_component_from_stack(tenant=self.tenant, stack=stack, component=c)
                for c in project.components.all()
            ]
            if any(removed):
                result.changed += 1
            else:
                result.unchanged += 1
        return result

    def attach_standard(self, projects, standard_id: str, importance_value: str = "") -> BulkEditResult:
        standard = self._standard(standard_id)
        chosen = importance.parse(importance_value) if importance_value else None
        result = self._result(f'Attached "{standard.name}" to')
        for project in projects:
            current = set(project.standards.values_list("pk", flat=True))
            if standard.pk in current and chosen is None:
                result.unchanged += 1
                continue
            importances = {str(standard.pk): chosen.value} if chosen else None
            project_management.set_project_standards(project, current | {standard.pk}, importances)
            result.changed += 1
        return result

    def detach_standard(self, projects, standard_id: str) -> BulkEditResult:
        standard = self._standard(standard_id)
        result = self._result(f'Detached "{standard.name}" from')
        for project in projects:
            if project.standards.filter(pk=standard.pk).exists():
                project_management.detach_standards(project, [standard.pk])
                result.changed += 1
            else:
                result.unchanged += 1
        return result

    def _stack(self, stack_id) -> Stack:
        try:
            return Stack.objects.get(tenant=self.tenant, pk=stack_id)
        except (Stack.DoesNotExist, ValidationError, ValueError):
            raise NotFoundError("Unknown stack.")

    def _standard(self, standard_id) -> Standard:
        try:
            return Standard.objects.get(tenant=self.tenant, pk=standard_id)
        except (Standard.DoesNotExist, ValidationError, ValueError):
            raise NotFoundError("Unknown standard.")
