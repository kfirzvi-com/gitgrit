from allauth.account.signals import email_confirmed
from django.contrib.auth.signals import user_logged_in
from django.db.models import QuerySet
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save

from app.application import superuser_service
from app.application.access import confirm_access_request_email
from app.application.membership_service import roster_of
from app.domain.models import ArtifactCommit, Component, Membership, Project, Tenant, User
from app.infrastructure import upload_storage
from app.domain.workspace_roles import OWNER
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


def delete_artifact_archive(sender, instance, **kwargs):
    """A deleted artifact commit takes its archive with it: deleting the
    project or its workspace cascades here, one commit at a time. Removed
    only once the deletion commits, so a rolled-back delete keeps its file."""
    key = instance.archive_key
    transaction.on_commit(lambda: upload_storage.delete_archive(key))


user_logged_in.connect(reset_support_view)
post_save.connect(create_root_component, sender=Project, dispatch_uid="project_root_component")
post_delete.connect(delete_artifact_archive, sender=ArtifactCommit, dispatch_uid="artifact_commit_archive")


# --- Invariant backstops ------------------------------------------------------
# The rules live in the domain (app.domain.workspace_roles, app.domain.superusers)
# and the services apply them. These catch the same changes when they bypass the
# services, the Django admin or a user's account being deleted, and ask the
# domain the same question.


def _deleting_model(origin):
    return origin.model if isinstance(origin, QuerySet) else type(origin)


def guard_last_owner_delete(sender, instance, origin=None, **kwargs):
    """Backstop for the workspace rules (``app.domain.workspace_roles``) when
    a membership disappears without going through the membership service: a
    user's account deleted, a row removed in the Django admin. Deleting the
    workspace itself takes its owners with it, which is fine."""
    if _deleting_model(origin) is Tenant:
        return
    roster_of(instance.tenant).ensure_can_lose(instance.user_id)


def guard_last_owner_save(sender, instance, raw=False, update_fields=None, **kwargs):
    """The same backstop for demoting an owner outside the service."""
    if raw or instance._state.adding or instance.role == OWNER:
        return
    if update_fields is not None and "role" not in update_fields:
        return
    old_role = (
        Membership.objects.filter(pk=instance.pk).values_list("role", flat=True).first()
    )
    if old_role == OWNER:
        roster_of(instance.tenant).ensure_can_lose(instance.user_id)


def guard_last_superuser_save(sender, instance, raw=False, update_fields=None, **kwargs):
    """Backstop for the superuser rules (``app.domain.superusers``) when an
    account stops being an active superuser outside the superuser service:
    unticked or deactivated in the Django admin."""
    if raw or instance._state.adding or (instance.is_superuser and instance.is_active):
        return
    if update_fields is not None and not {"is_superuser", "is_active"} & set(update_fields):
        return
    if User.objects.filter(pk=instance.pk, is_superuser=True, is_active=True).exists():
        superuser_service.current().ensure_can_lose(instance.pk)


def guard_last_superuser_delete(sender, instance, **kwargs):
    if instance.is_superuser and instance.is_active:
        superuser_service.current().ensure_can_lose(instance.pk)


pre_delete.connect(guard_last_owner_delete, sender=Membership, dispatch_uid="membership_last_owner_delete")
pre_save.connect(guard_last_owner_save, sender=Membership, dispatch_uid="membership_last_owner_save")
pre_save.connect(guard_last_superuser_save, sender=User, dispatch_uid="user_last_superuser_save")
pre_delete.connect(guard_last_superuser_delete, sender=User, dispatch_uid="user_last_superuser_delete")


# --- allauth --------------------------------------------------------------------


def access_request_email_confirmed(sender, request, email_address, **kwargs):
    """A pending sign-up followed their confirmation link: their access
    request can now reach superusers."""
    confirm_access_request_email(email_address.user)


email_confirmed.connect(access_request_email_confirmed, dispatch_uid="access_request_email_confirmed")
