from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from app.domain.models import Membership, PlatformConnection, Policy, PolicyExecution, Project


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

            # Recent executions across all tenant projects
            tenant_projects = Project.objects.filter(tenant=tenant)
            recent_executions = PolicyExecution.objects.filter(
                project__in=tenant_projects
            ).select_related("policy", "project")[:10]
            context["recent_executions"] = recent_executions

            # Compliance score: average of latest-per-policy scores across all projects
            all_executions = PolicyExecution.objects.filter(
                project__in=tenant_projects
            ).select_related("policy").order_by("-created_at")[:200]
            seen = {}
            for ex in all_executions:
                key = (ex.project_id, ex.policy_id or ex.policy_name)
                if key not in seen:
                    seen[key] = ex
            latest = list(seen.values())
            if latest:
                context["compliance_score"] = round(
                    sum(ex.score for ex in latest) / len(latest)
                )
            else:
                context["compliance_score"] = None
        else:
            context["project_count"] = 0
            context["policy_count"] = 0
            context["recent_executions"] = []
            context["compliance_score"] = None
        return context
