from django.conf import settings

from app.domain.models import Tenant


def version_context(request):
    """Build-time version info baked into the Docker image. Used by the
    base template's footer to surface a "you're running commit X" link."""
    return {
        "git_sha": settings.GIT_SHA,
        "git_tag": settings.GIT_TAG,
        "git_sha_short": settings.GIT_SHA[:7] if settings.GIT_SHA else "",
        "github_repo_url": "https://github.com/kfirzvi-com/gitgrit",
    }


def tenant_context(request):
    ctx = {
        "airgapped": settings.AIRGAPPED,
        "site_url": settings.SITE_URL,
        "auth_provider_github_enabled": settings.AUTH_PROVIDER_GITHUB_ENABLED,
        "auth_provider_gitlab_enabled": settings.AUTH_PROVIDER_GITLAB_ENABLED,
        "auth_provider_google_enabled": settings.AUTH_PROVIDER_GOOGLE_ENABLED,
    }

    if not hasattr(request, "user") or not request.user.is_authenticated:
        return ctx

    ctx.update({
        "current_tenant": getattr(request, "tenant", None),
        "user_tenants": Tenant.objects.filter(
            memberships__user=request.user
        ).order_by("created_at"),
    })
    return ctx
