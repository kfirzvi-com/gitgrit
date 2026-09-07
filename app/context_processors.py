from django.conf import settings

from app.domain.models import Membership

# Users with this many workspaces or fewer get a plain list; above it the
# switcher shows a search box.
WORKSPACE_SEARCH_THRESHOLD = 4


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

    # The switcher's rows are lazy-loaded by workspace_switcher_list when the
    # dropdown opens, so pages only pay for a count here.
    workspace_count = Membership.objects.filter(user=request.user).count()
    ctx.update({
        "current_tenant": getattr(request, "tenant", None),
        "workspace_count": workspace_count,
        "show_workspace_search": workspace_count > WORKSPACE_SEARCH_THRESHOLD,
    })
    return ctx
