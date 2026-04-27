import json

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from app.domain.models import APIToken


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

        tenant = self.request.tenant
        ctx["tenant"] = tenant
        if tenant:
            ctx["api_tokens"] = APIToken.objects.filter(
                user=self.request.user, tenant=tenant
            ).order_by("-created_at")

        ctx["new_token_value"] = self.request.session.pop("new_token_value", None)
        ctx["new_token_name"] = self.request.session.pop("new_token_name", None)
        ctx["new_token_kind"] = self.request.session.pop("new_token_kind", None)

        site_url = settings.SITE_URL.rstrip("/")
        mcp_url = f"{site_url}/mcp/"
        ctx["mcp_url"] = mcp_url
        ctx["mcp_config_desktop"] = json.dumps(
            {
                "mcpServers": {
                    "GitGrit": {
                        "url": mcp_url,
                        "authorization_token": "YOUR_TOKEN",
                    }
                }
            },
            indent=2,
        )
        ctx["mcp_config_code"] = json.dumps(
            {
                "mcpServers": {
                    "GitGrit": {
                        "url": mcp_url,
                        "headers": {"Authorization": "Bearer YOUR_TOKEN"},
                    }
                }
            },
            indent=2,
        )
        ctx["mcp_config_generic"] = json.dumps(
            {
                "mcpServers": {
                    "GitGrit": {
                        "url": mcp_url,
                        "headers": {"Authorization": "Bearer YOUR_TOKEN"},
                    }
                }
            },
            indent=2,
        )
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
