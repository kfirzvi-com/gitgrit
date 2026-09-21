"""Stack membership use cases.

Thin application services that own the writes for stack creation and
component↔stack membership, and raise domain events within the transaction so
the graph subscriber's enqueue is atomic with the change.

A stack groups *components* (the deployable units inside repositories), not
projects: a monorepo's services can belong to different stacks. For a plain
single-application repository the only component is the root one, so adding
"the project" to a stack means adding its root component.
"""
from __future__ import annotations

from django.db import transaction

from app.application.event_bus import publish
from app.domain.events import (
    ComponentAddedToStack,
    ComponentRemovedFromStack,
    StackCreated,
)
from app.domain.models import Component, ComponentStack, Stack


def create_stack(*, tenant, name: str, description: str = "") -> Stack:
    with transaction.atomic():
        stack = Stack.objects.create(tenant=tenant, name=name, description=description)
        publish(StackCreated(stack_id=str(stack.id), tenant_id=str(tenant.id)))
    return stack


def update_stack(*, stack: Stack, name: str, description: str = "") -> Stack:
    stack.name = name
    stack.description = description
    stack.save(update_fields=["name", "description", "updated_at"])
    return stack


def add_component_to_stack(*, tenant, stack, component) -> bool:
    """Add component to stack. Returns True if newly added (else already present)."""
    with transaction.atomic():
        _, created = ComponentStack.objects.get_or_create(component=component, stack=stack)
        if created:
            publish(
                ComponentAddedToStack(
                    component_id=str(component.id),
                    project_id=str(component.project_id),
                    stack_id=str(stack.id),
                    tenant_id=str(tenant.id),
                )
            )
    return created


def remove_component_from_stack(*, tenant, stack, component) -> bool:
    """Remove component from stack. Returns True if a membership was removed."""
    with transaction.atomic():
        deleted, _ = ComponentStack.objects.filter(component=component, stack=stack).delete()
        if deleted:
            publish(
                ComponentRemovedFromStack(
                    component_id=str(component.id),
                    project_id=str(component.project_id),
                    stack_id=str(stack.id),
                    tenant_id=str(tenant.id),
                )
            )
    return bool(deleted)


def set_stack_components(*, tenant, stack, components) -> tuple[int, int]:
    """Replace the stack's membership with ``components``.

    Adds and removes go through the single-component use cases so the graph
    events fire for each change. Returns ``(added, removed)`` counts.
    """
    wanted = {c.pk: c for c in components}
    current = {
        c.pk: c for c in Component.objects.filter(tenant=tenant, stacks=stack)
    }
    added = removed = 0
    with transaction.atomic():
        for pk, component in wanted.items():
            if pk not in current:
                added += add_component_to_stack(tenant=tenant, stack=stack, component=component)
        for pk, component in current.items():
            if pk not in wanted:
                removed += remove_component_from_stack(
                    tenant=tenant, stack=stack, component=component
                )
    return added, removed


def add_project_to_stacks(*, tenant, project, stacks) -> int:
    """Put a freshly added project's root component into ``stacks``.

    The add-project form offers stacks before any analysis has run, when the
    only component is the root one. Returns the number of memberships added.
    """
    root = project.root_component
    if root is None:
        return 0
    return sum(
        add_component_to_stack(tenant=tenant, stack=stack, component=root)
        for stack in stacks
    )
