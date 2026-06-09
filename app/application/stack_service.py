"""Stack membership use cases.

Thin application services that own the writes for stack creation and
project↔stack membership, and raise domain events within the transaction so
the graph subscriber's enqueue is atomic with the change.
"""
from __future__ import annotations

from django.db import transaction

from app.application.event_bus import publish
from app.domain.events import (
    ProjectAddedToStack,
    ProjectRemovedFromStack,
    StackCreated,
)
from app.domain.models import ProjectStack, Stack


def create_stack(*, tenant, name: str, description: str = "") -> Stack:
    with transaction.atomic():
        stack = Stack.objects.create(tenant=tenant, name=name, description=description)
        publish(StackCreated(stack_id=str(stack.id), tenant_id=str(tenant.id)))
    return stack


def add_project_to_stack(*, tenant, stack, project) -> bool:
    """Add project to stack. Returns True if newly added (else already present)."""
    with transaction.atomic():
        _, created = ProjectStack.objects.get_or_create(project=project, stack=stack)
        if created:
            publish(
                ProjectAddedToStack(
                    project_id=str(project.id),
                    stack_id=str(stack.id),
                    tenant_id=str(tenant.id),
                )
            )
    return created


def remove_project_from_stack(*, tenant, stack, project) -> bool:
    """Remove project from stack. Returns True if a membership was removed."""
    with transaction.atomic():
        deleted, _ = ProjectStack.objects.filter(project=project, stack=stack).delete()
        if deleted:
            publish(
                ProjectRemovedFromStack(
                    project_id=str(project.id),
                    stack_id=str(stack.id),
                    tenant_id=str(tenant.id),
                )
            )
    return bool(deleted)
