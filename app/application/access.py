"""Who gets into GitGrit: first-run setup, gated signup and its approval.

A deployment starts with no users and is claimed by whoever completes
first-run setup with the setup token; that person becomes the first superuser.
After that, ``settings.SIGNUP_MODE`` decides what a signup gets:

* ``open`` — straight in.
* ``approval`` — an inactive user and a pending ``AccessRequest``; superusers
  are emailed at once.
* ``onboarding`` — the same, but superusers are emailed only once the person
  has filled in the request-access form, so the email carries their answers.

Approving activates the user, puts them in a workspace the approver picks
(an existing one, or a new one for their company) and emails them. Nobody gets
a workspace of their own just for signing up — not even the first admin, who
creates workspaces from there.
"""
import hashlib
import hmac
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.urls import reverse

from app.application.membership_service import add_member
from app.application.workspace_service import create_workspace
from app.domain.models import AccessRequest, Tenant

logger = logging.getLogger("app.access")

# Arbitrary, fixed key for the advisory lock that serialises first-run setup.
_SETUP_LOCK_KEY = 0x6717_5E70


class SetupAlreadyDone(Exception):
    """First-run setup was attempted on a deployment that already has users."""


# --- configuration ---------------------------------------------------------


def signup_is_gated() -> bool:
    return settings.SIGNUP_MODE != "open"


def onboarding_form_required() -> bool:
    return settings.SIGNUP_MODE == "onboarding"


# --- first run -------------------------------------------------------------


def setup_required() -> bool:
    return settings.FIRST_RUN_SETUP_ENABLED and not get_user_model().objects.exists()


def setup_token() -> str:
    """The token first-run setup asks for. Set explicitly via
    ``GITGRIT_SETUP_TOKEN``, or derived from ``SECRET_KEY`` so every worker
    process and every restart agree on it without storing anything."""
    if settings.GITGRIT_SETUP_TOKEN:
        return settings.GITGRIT_SETUP_TOKEN
    digest = hmac.new(
        settings.SECRET_KEY.encode(), b"gitgrit-first-run-setup", hashlib.sha256
    ).hexdigest()
    return digest[:24]


def setup_token_matches(candidate: str) -> bool:
    return hmac.compare_digest((candidate or "").strip(), setup_token())


def create_first_admin(email: str, password: str):
    """Create the first superuser and their workspace.

    Two people submitting setup at once must not both become admin, so the
    emptiness check and the insert run under one transaction-scoped advisory
    lock: the second caller waits, then sees a user and gets
    ``SetupAlreadyDone``.
    """
    from allauth.account.models import EmailAddress
    from allauth.account.adapter import get_adapter

    User = get_user_model()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_SETUP_LOCK_KEY])
        if User.objects.exists():
            raise SetupAlreadyDone()
        user = User(email=email, is_staff=True, is_superuser=True)
        get_adapter().populate_username(None, user)
        user.set_password(password)
        user.save()
        EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
    logger.warning("first-run setup: superuser %s (%s) created", user.pk, email)
    return user


# --- password signup -------------------------------------------------------


def register_with_password(email: str, password: str):
    """Sign someone up from the email + password box on the sign-in page.

    On a gated deployment they arrive inactive with a pending request, exactly
    like a provider signup. Nothing has proven they own the address, so the
    ``EmailAddress`` is unverified; the approver sees that.
    """
    from allauth.account.adapter import get_adapter
    from allauth.account.models import EmailAddress

    with transaction.atomic():
        user = get_user_model()(email=email, is_active=not signup_is_gated())
        get_adapter().populate_username(None, user)
        user.set_password(password)
        user.save()
        EmailAddress.objects.create(user=user, email=email, primary=True, verified=False)
        if not user.is_active:
            open_access_request(user)
    return user


# --- access requests -------------------------------------------------------


def open_access_request(user) -> AccessRequest:
    """Record a gated signup. ``user`` was just created inactive."""
    access_request = AccessRequest.objects.create(user=user)
    if not onboarding_form_required():
        _notify_reviewers(access_request)
    return access_request


def submit_access_request(access_request: AccessRequest, answers: dict) -> None:
    access_request.submit(answers)
    access_request.save(update_fields=["answers", "submitted_at"])
    _notify_reviewers(access_request)


def approve_access_request(
    access_request: AccessRequest,
    reviewer,
    *,
    role: str,
    workspace: Tenant | None = None,
    new_workspace_name: str = "",
) -> Tenant:
    """Let the person in, as ``role`` in ``workspace`` — or in a new workspace
    called ``new_workspace_name``. Exactly one of the two. The workspace rules
    (``app.domain.workspace_roles``) may still refuse the role; nothing is
    approved then."""
    if bool(workspace) == bool(new_workspace_name.strip()):
        raise ValueError("Pick an existing workspace or name a new one, not both.")

    with transaction.atomic():
        access_request.approve(reviewer)
        access_request.user.save(update_fields=["is_active"])
        access_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        if workspace is None:
            workspace = create_workspace(
                new_workspace_name.strip(), access_request.user, by=reviewer, role=role
            )
        else:
            add_member(workspace, access_request.user, role, by=reviewer)
        _send_email(
            "access_approved",
            [access_request.user.email],
            {
                "name": access_request.answers.get("name", ""),
                "workspace": workspace.name,
                "login_path": reverse("account_login"),
            },
        )
    logger.info(
        "access request %s for %s approved by %s into workspace %s as %s",
        access_request.pk,
        access_request.user.email,
        reviewer.pk,
        workspace.slug,
        role,
    )
    return workspace


def reject_access_request(access_request: AccessRequest, reviewer) -> None:
    with transaction.atomic():
        access_request.reject(reviewer)
        access_request.user.save(update_fields=["is_active"])
        access_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    logger.info(
        "access request %s for %s rejected by %s",
        access_request.pk,
        access_request.user.email,
        reviewer.pk,
    )


def pending_access_request_count() -> int:
    return AccessRequest.objects.filter(status=AccessRequest.Status.PENDING).count()


def _notify_reviewers(access_request: AccessRequest) -> None:
    reviewers = list(
        get_user_model()
        .objects.filter(is_superuser=True, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    _send_email(
        "access_requested",
        reviewers,
        {
            "email": access_request.user.email,
            "answers": access_request.answers,
            "review_path": reverse("access_request_list"),
        },
    )


def _send_email(template: str, to: list[str], context: dict) -> None:
    """Queue the email once the surrounding transaction commits, so a rolled
    back approval never tells anyone they are in."""
    if not to:
        return
    from app.tasks import send_email

    transaction.on_commit(
        lambda: send_email.defer(template=template, to=to, context=context)
    )
