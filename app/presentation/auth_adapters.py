"""allauth adapters: where gated signup hooks into the login flow.

* allauth's own signup form is closed in every mode. Password signup goes
  through the sign-in page instead: an unknown email there signs up
  (``EmailAwareLoginView``).

On a gated deployment (``settings.SIGNUP_MODE`` other than ``open``):

* A provider signup creates the user inactive, with a pending
  ``AccessRequest``.
* allauth refuses inactive users at login and hands them to
  ``respond_user_inactive``. For someone with an access request that sends
  them to their request page (the onboarding form, or its status), which finds
  them through a session key set here — they have just proven who they are to
  the provider, but they are not, and must not be, logged in.
* An email + password signup must confirm the address first. The
  confirmation link lands on the same request page.

Every email allauth sends (confirmation, password reset) goes through our
outbox instead of allauth's mailer, so it renders on GitGrit's branded layout
and is sent by the worker, not inside the request.
"""
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
import logging

from django.shortcuts import redirect
from django.template.loader import get_template
from django.template.exceptions import TemplateDoesNotExist
from django.urls import reverse

from app.application.access import open_access_request, signup_is_gated
from app.application.outbox import send_later
from app.domain.models import AccessRequest

logger = logging.getLogger("app.access")

# allauth hands its emails a context full of objects (the request, the user,
# the site); the worker gets JSON. These are the values our templates use.
_ALLAUTH_MAIL_KEYS = ("activate_url", "password_reset_url", "signup_url", "email")

PENDING_USER_SESSION_KEY = "pending_access_user_id"
# The token of the invitation link the person arrived with
# (app.presentation.views.invitation_views). Signing up or in with the invited
# address takes the invitation instead of opening an access request.
INVITATION_SESSION_KEY = "invitation_token"


def _session_invitation(request, email):
    """The open invitation from this session's link, if it's for ``email``."""
    from app.application import invitations

    if request is None or not email:
        return None
    found = invitations.find_open(request.session.get(INVITATION_SESSION_KEY, ""))
    return found if found is not None and found.is_for([email]) else None


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False

    def respond_user_inactive(self, request, user):
        found = _session_invitation(request, user.email)
        if found is not None:
            # Still waiting for approval, but invited: the invitation lets
            # them in (and the link proved their address).
            from django.contrib.auth import login

            from app.application import invitations
            from app.presentation.views.invitation_views import enter_workspace

            invitations.accept(found, user, via_link=True)
            user.refresh_from_db()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            enter_workspace(request, found)
            return redirect("dashboard")
        if AccessRequest.objects.filter(user=user).exists():
            request.session[PENDING_USER_SESSION_KEY] = str(user.pk)
            return redirect("access_request_status")
        return super().respond_user_inactive(request, user)

    def get_email_verification_redirect_url(self, email_address):
        """Following the confirmation link proves who they are, as a provider
        sign-in would: show them their access request."""
        user = email_address.user
        if not user.is_active and AccessRequest.objects.filter(user=user).exists():
            self.request.session[PENDING_USER_SESSION_KEY] = str(user.pk)
            return reverse("access_request_status")
        return super().get_email_verification_redirect_url(email_address)

    def send_mail(self, template_prefix, email, context):
        """allauth's emails, on our layout and through the worker. One of
        ours must exist for each (email/<name>.html etc., where <name> is the
        last part of allauth's ``account/email/<name>``); an email we have no
        template for is sent the allauth way and logged, so it isn't lost."""
        name = template_prefix.rsplit("/", 1)[-1]
        try:
            get_template(f"email/{name}.html")
        except TemplateDoesNotExist:
            logger.warning("no branded template for allauth email %s", template_prefix)
            return super().send_mail(template_prefix, email, context)
        ctx = {key: str(context[key]) for key in _ALLAUTH_MAIL_KEYS if context.get(key)}
        user = context.get("user")
        if user is not None:
            ctx["name"] = user.get_full_name() or ""
        ctx.setdefault("email", email)
        send_later(name, [email], ctx)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        # Provider signup stays open on a gated deployment; what the new user
        # gets is decided below.
        return True

    def new_user(self, request, sociallogin):
        user = super().new_user(request, sociallogin)
        if signup_is_gated():
            user.is_active = False
        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        found = _session_invitation(request, user.email)
        if found is not None:
            # Signed up from an invitation link with the invited address:
            # that's accepting it, and it lets them in.
            from app.application import invitations
            from app.presentation.views.invitation_views import enter_workspace

            invitations.accept(found, user, via_link=True)
            user.refresh_from_db()
            enter_workspace(request, found)
        elif not user.is_active:
            open_access_request(user)
        return user
