import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from app.domain.models import PlatformConnection, PolicyExecution, Project
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger(__name__)


class ProjectListView(LoginRequiredMixin, ListView):
    template_name = "pages/project_list.html"
    context_object_name = "projects"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Project.objects.none()
        return Project.objects.filter(tenant=tenant).select_related(
            "platform_connection"
        )


class ProjectDetailView(LoginRequiredMixin, DetailView):
    template_name = "pages/project_detail.html"
    context_object_name = "project"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Project.objects.none()
        return Project.objects.filter(tenant=tenant).select_related(
            "platform_connection"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.object

        recent_executions = PolicyExecution.objects.filter(
            project=project
        ).select_related("policy")[:50]
        context["recent_executions"] = recent_executions

        # Deduplicate: latest execution per policy
        seen_policies = {}
        for ex in recent_executions:
            key = ex.policy_id or ex.policy_name
            if key not in seen_policies:
                seen_policies[key] = ex
        latest_executions = list(seen_policies.values())
        context["latest_executions"] = latest_executions

        # Compliance score: average of latest-per-policy scores
        if latest_executions:
            context["compliance_score"] = round(
                sum(ex.score for ex in latest_executions) / len(latest_executions)
            )
        else:
            context["compliance_score"] = None

        return context


@login_required
def add_project_select(request):
    """Step 1: Select a platform connection."""
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")

    connections = PlatformConnection.objects.filter(tenant=tenant).order_by(
        "created_at"
    )
    if not connections.exists():
        messages.warning(
            request,
            "Add a platform connection in workspace settings before adding projects.",
        )
        return redirect("tenant_settings")

    return render(
        request,
        "pages/add_project.html",
        {"step": "select_connection", "connections": connections},
    )


@login_required
def add_project_search(request, connection_id):
    """Step 2: Search projects and fill metadata."""
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")

    connection = get_object_or_404(
        PlatformConnection, id=connection_id, tenant=tenant
    )

    if request.method == "POST":
        external_id = request.POST.get("external_id", "").strip()
        name = request.POST.get("name", "").strip()
        full_path = request.POST.get("full_path", "").strip()
        web_url = request.POST.get("web_url", "").strip()
        default_branch = request.POST.get("default_branch", "main").strip()
        description = request.POST.get("description", "").strip()
        lifecycle = request.POST.get("lifecycle", Project.Lifecycle.DEVELOPMENT)

        if not external_id or not name:
            messages.error(request, "Please select a project.")
            return redirect("add_project_search", connection_id=connection_id)

        if Project.objects.filter(
            tenant=tenant, platform_connection=connection, external_id=external_id
        ).exists():
            messages.warning(request, f'"{name}" is already added to this workspace.')
            return redirect("project_list")

        project = Project.objects.create(
            tenant=tenant,
            platform_connection=connection,
            platform=connection.platform,
            external_id=external_id,
            name=name,
            full_path=full_path,
            web_url=web_url,
            default_branch=default_branch,
            description=description,
            lifecycle=lifecycle,
        )
        messages.success(request, f'Project "{project.name}" added.')
        return redirect("project_detail", pk=project.pk)

    return render(
        request,
        "pages/add_project.html",
        {
            "step": "search",
            "connection": connection,
            "lifecycle_choices": Project.Lifecycle.choices,
        },
    )


@login_required
def search_projects_api(request):
    """Search endpoint for HTMX — returns HTML partial or JSON."""
    tenant = request.tenant
    if not tenant:
        return JsonResponse({"results": []})

    connection_id = request.GET.get("connection_id")
    query = request.GET.get("q", "").strip()

    connection = PlatformConnection.objects.filter(
        id=connection_id, tenant=tenant
    ).first()
    if not connection:
        return JsonResponse({"results": []})

    try:
        client = get_platform_client(connection)
        results = client.search_projects(query)
        existing_ids = set(
            Project.objects.filter(
                tenant=tenant, platform_connection=connection
            ).values_list("external_id", flat=True)
        )
        for r in results:
            r["already_added"] = r["external_id"] in existing_ids

        results = results[:25]

        if request.headers.get("HX-Request"):
            return render(
                request,
                "partials/project_search_results.html",
                {"results": results},
            )
        return JsonResponse({"results": results})
    except Exception:
        logger.exception("Failed to search projects")
        if request.headers.get("HX-Request"):
            from django.http import HttpResponse

            return HttpResponse(
                '<p class="text-sm text-error">Failed to search platform API. '
                "Check your connection token.</p>"
            )
        return JsonResponse({"results": [], "error": "Failed to search platform API"})


@login_required
@require_POST
def delete_project(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")

    project = get_object_or_404(Project, pk=pk, tenant=tenant)
    name = project.name
    project.delete()
    messages.success(request, f'Project "{name}" removed.')
    return redirect("project_list")
