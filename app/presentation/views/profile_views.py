from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from app.application.user_time_zone_setting import ask_for_time_zone, change_time_zone
from app.domain.models import APIToken
from app.domain.user_time_zone import UTC, UnknownTimeZone, UserTimeZone
from app.presentation.htmx import toast


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "pages/profile.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        social_accounts = SocialAccount.objects.filter(user=self.request.user)
        connected = {sa.provider: sa for sa in social_accounts}

        providers = []
        for provider_id, label, icon in [
            ("github", "GitHub", "github"),
            ("gitlab", "GitLab", "gitlab"),
            ("google", "Google", "google"),
        ]:
            account = connected.get(provider_id)
            providers.append({
                "id": provider_id,
                "label": label,
                "icon": icon,
                "connected": account is not None,
                "username": _get_display_name(provider_id, account) if account else None,
                "uid": account.uid if account else None,
            })

        ctx["providers"] = providers
        ctx["time_zones"] = UserTimeZone.names()
        ctx["current_time_zone"] = self.request.user.user_time_zone.name
        # The picker is right here; the question would only repeat it.
        ctx["hide_time_zone_question"] = True

        ctx["api_tokens"] = APIToken.objects.filter(
            kind=APIToken.Kind.PERSONAL, user=self.request.user
        )
        ctx["new_token_value"] = self.request.session.pop("new_token_value", None)
        ctx["new_token_name"] = self.request.session.pop("new_token_name", None)
        return ctx


@login_required
@require_POST
def disconnect_social(request, provider):
    account = get_object_or_404(
        SocialAccount, user=request.user, provider=provider
    )
    account.delete()
    messages.success(request, f"Disconnected {provider}.")
    return redirect("profile")


@login_required
@require_POST
def update_time_zone(request):
    """The signed-in user picks their own time zone: from the Profile picker,
    or in place from the time zone question (which then goes away)."""
    try:
        zone = change_time_zone(request.user, request.POST.get("time_zone", ""))
        text, level = f"Time zone set to {zone.name}.", "success"
    except UnknownTimeZone:
        text, level = "Pick a time zone from the list.", "error"
    if request.htmx:
        response = toast(HttpResponse(""), text, level)
        if level == "error":
            response["HX-Reswap"] = "none"  # keep the question, so they can answer again
        return response
    getattr(messages, level)(request, text)
    return redirect("profile")


@login_required
@require_POST
def time_zone_question(request):
    """The time zone question for the device's zone, once (rule 6), or
    nothing when there is nothing to ask."""
    tenant = getattr(request, "tenant", None)
    zone = ask_for_time_zone(
        request.user, request.POST.get("device_time_zone", ""), tenant.pk if tenant else None
    )
    if zone is None:
        return HttpResponse("")
    return render(request, "components/time_zone_question.html", {"zone": zone, "utc": UTC})


def _get_display_name(provider, social_account):
    """Extract a human-readable name from the social account extra_data."""
    data = social_account.extra_data or {}
    if provider == "github":
        return data.get("login") or data.get("name") or social_account.uid
    elif provider == "gitlab":
        return data.get("username") or data.get("name") or social_account.uid
    elif provider == "google":
        return data.get("email") or data.get("name") or social_account.uid
    return social_account.uid
