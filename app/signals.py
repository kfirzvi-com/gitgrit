from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save, pre_delete, pre_save

from app.application.membership_service import (
    guard_last_owner_delete,
    guard_last_owner_save,
)
from app.domain.models import Component, Membership, Project
from app.workspace_access import leave_support_view


def reset_support_view(request, user, **kwargs):
    """A login always starts in the user's own workspace. Django keeps session
    data when the same user logs in again, so a support view left in the
    session would otherwise resume in a customer's workspace."""
    if request is not None and hasattr(request, "session"):
        leave_support_view(request)


def create_root_component(sender, instance, created, raw=False, **kwargs):
    """Every project has at least one component: the repository root.

    Created with the project so stack membership and the dependency graph
    always have a component to attach to, before any analysis has run. The
    inference agent later reconciles the component set by path, which keeps
    this root row (and its id) for single-application repositories.
    ``raw`` is True during fixture loading, where the fixture owns the rows.
    """
    if not created or raw:
        return
    Component.objects.get_or_create(
        project=instance,
        path="",
        defaults={"tenant_id": instance.tenant_id, "name": instance.name},
    )


user_logged_in.connect(reset_support_view)
post_save.connect(create_root_component, sender=Project, dispatch_uid="project_root_component")
pre_delete.connect(guard_last_owner_delete, sender=Membership, dispatch_uid="membership_last_owner_delete")
pre_save.connect(guard_last_owner_save, sender=Membership, dispatch_uid="membership_last_owner_save")
