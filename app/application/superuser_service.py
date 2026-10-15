"""Making and unmaking superusers: load the current superusers, let the
domain decide (``app.domain.superusers``), store the outcome and publish it.

The superuser rows are locked for the decision, so two superusers revoking
each other at the same moment can't both see the other as the one left.
"""
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from app.application.event_bus import publish
from app.domain.superusers import Account, Superusers

logger = logging.getLogger("app.access")


def _active_superusers():
    User = get_user_model()
    return User.objects.filter(is_superuser=True, is_active=True)


def current() -> Superusers:
    return Superusers(_active_superusers().values_list("pk", flat=True))


def account(user) -> Account:
    return Account(str(user.pk), is_active=user.is_active, is_superuser=user.is_superuser)


def _locked() -> Superusers:
    return Superusers(
        str(pk) for pk in _active_superusers().select_for_update().values_list("pk", flat=True)
    )


def grant(user, by):
    """Make ``user`` a superuser. Django's admin needs is_staff too, so the
    two move together."""
    with transaction.atomic():
        event = _locked().grant(str(by.pk), account(user))
        user.is_superuser = True
        user.is_staff = True
        user.superuser_granted_by = by
        user.superuser_granted_at = timezone.now()
        user.save(
            update_fields=["is_superuser", "is_staff", "superuser_granted_by", "superuser_granted_at"]
        )
    logger.warning("superuser granted: %s (%s) by %s", user.pk, user.email, by.pk)
    publish(event)
    return user


def revoke(user, by):
    with transaction.atomic():
        event = _locked().revoke(str(by.pk), account(user))
        user.is_superuser = False
        user.is_staff = False
        user.superuser_granted_by = None
        user.superuser_granted_at = None
        user.save(
            update_fields=["is_superuser", "is_staff", "superuser_granted_by", "superuser_granted_at"]
        )
    logger.warning("superuser revoked: %s (%s) by %s", user.pk, user.email, by.pk)
    publish(event)
    return user
