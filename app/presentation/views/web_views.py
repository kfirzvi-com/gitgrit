from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from app.application.cockpit import Cockpit, HealthTrend
from app.application.dependency_agent import refresh_workspace_map
from app.application.project_health_counts import ProjectHealthCounts
from app.domain.models import PlatformConnection, Standard, Project, Stack
from app.presentation.architecture import map_status, stack_dependencies
from app.presentation.health_dial import HealthDial
from app.presentation.health_note import HealthNote
from app.presentation.speedometer import Speedometer
from app.presentation.stack_map import StackMap
from app.presentation.trend_chart import TrendChart
from app.workspace_access import is_workspace_admin


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

            cockpit = Cockpit.for_workspace(tenant)
            context["cockpit"] = cockpit
            context["workspace_health"] = cockpit.health
            context["dial"] = HealthDial.segments(cockpit.health)
            context["attention_rows"] = [
                (row, HealthNote.text(row.score, row.below_par)) for row in cockpit.rows
            ]
            context["trend"] = TrendChart(HealthTrend.weekly(tenant))
            context["speedometer"] = Speedometer(cockpit.checks_this_week, cockpit.checks_peak)

            stacks = list(Stack.objects.filter(tenant=tenant).prefetch_related("components__project"))
            health = ProjectHealthCounts.for_stacks(stacks)
            # Worst first: most failed, then most needing attention, then by name.
            context["stack_health"] = sorted(
                ((stack, health[stack.pk]) for stack in stacks),
                key=lambda row: (-row[1].failed, -row[1].needs_attention, row[0].name.lower()),
            )
            context["stack_map"] = StackMap(context["stack_health"], stack_dependencies(tenant, stacks))
            context["map_updated_at"] = map_status(Project.objects.filter(tenant=tenant))["updated_at"]
        else:
            context["project_count"] = 0
            context["standard_count"] = 0
            context["stack_count"] = 0
            context["workspace_health"] = None
            context["stack_health"] = []
            context["cockpit"] = None
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

