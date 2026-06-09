import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from app.domain.models import Membership, PlatformConnection, Policy, Project, Stack
from app.presentation.architecture import latest_scores_by_project, workspace_graph


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
            membership = Membership.objects.filter(
                user=self.request.user, tenant=tenant
            ).first()
            context["is_admin"] = membership and membership.role in (
                Membership.Role.OWNER,
                Membership.Role.ADMIN,
            )
            context["has_connections"] = PlatformConnection.objects.filter(
                tenant=tenant
            ).exists()
            context["project_count"] = Project.objects.filter(tenant=tenant).count()
            context["policy_count"] = Policy.objects.filter(
                tenant=tenant, enabled=True
            ).count()
            context["stack_count"] = Stack.objects.filter(tenant=tenant).count()

            latest = latest_scores_by_project(tenant)
            all_scores = [
                result["score"]
                for results in latest.values()
                for result in results.values()
            ]
            context["compliance_score"] = (
                round(sum(all_scores) / len(all_scores)) if all_scores else None
            )
            context["architecture_data"] = json.dumps(workspace_graph(tenant, latest))
        else:
            context["project_count"] = 0
            context["policy_count"] = 0
            context["stack_count"] = 0
            context["compliance_score"] = None
            context["architecture_data"] = json.dumps(
                {"stacks": [], "dependencies": []}
            )
        return context
