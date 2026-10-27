
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from app.application.dependency_agent import refresh_workspace_map
from app.application.standard_results import attention_items
from app.application.project_health_counts import ProjectHealthCounts
from app.domain.models import PlatformConnection, Standard, Project, Stack
from app.workspace_access import is_workspace_admin
from app.presentation.architecture import (
    workspace_graph,
    workspace_map_status,
)


class HomeView(TemplateView):
    template_name = "pages/home.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "pages/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant

        if tenant:
            context["is_admin"] = is_workspace_admin(self.request)
            context["has_connections"] = PlatformConnection.objects.filter(
                tenant=tenant
            ).exists()
            context["project_count"] = Project.objects.filter(tenant=tenant).count()
            context["standard_count"] = Standard.objects.filter(
                tenant=tenant, enabled=True
            ).count()
            context["stack_count"] = Stack.objects.filter(tenant=tenant).count()

            context["workspace_health"] = ProjectHealthCounts.for_workspace(tenant)
            context["architecture_data"] = workspace_graph(tenant)
            map_status = workspace_map_status(tenant)
            context["map_updated_at"] = map_status["updated_at"]
            context["map_analyzing"] = map_status["analyzing"]
            attention = attention_items(tenant)
            context["attention_items"] = attention
            context["attention_total"] = len(attention)
        else:
            context["project_count"] = 0
            context["standard_count"] = 0
            context["stack_count"] = 0
            context["workspace_health"] = None
            context["architecture_data"] = {"stacks": [], "dependencies": []}
            context["attention_items"] = []
            context["attention_total"] = 0
        return context


@login_required
@require_POST
def refresh_map(request):
    """Rebuild the dashboard map from every project's main branch (queued;
    the worker does the reading). Superusers only: it costs one LLM run per
    project."""
    if not request.user.is_superuser:
        raise PermissionDenied
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("dashboard")

    queued = refresh_workspace_map(tenant)
    if queued:
        messages.success(
            request,
            f"Refreshing the map from the main branch of {queued} "
            f"project{'' if queued == 1 else 's'}. It updates as each one finishes.",
        )
    else:
        messages.warning(request, "No projects to refresh.")
    return redirect("dashboard")
