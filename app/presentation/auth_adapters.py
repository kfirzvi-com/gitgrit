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
"""
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.shortcuts import redirect

from app.application.access import open_access_request, signup_is_gated
from app.domain.models import AccessRequest

PENDING_USER_SESSION_KEY = "pending_access_user_id"


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False

    def respond_user_inactive(self, request, user):
        if AccessRequest.objects.filter(user=user).exists():
            request.session[PENDING_USER_SESSION_KEY] = str(user.pk)
            return redirect("access_request_status")
        return super().respond_user_inactive(request, user)


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
        if not user.is_active:
            open_access_request(user)
        return user
