import logging
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from app.application.policy_engine import PolicyEngine
from app.domain.models import PlatformConnection, Policy, PolicyExecution, Project, Stack
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger(__name__)


def _existing_owners(tenant):
    return list(
        Project.objects.filter(tenant=tenant)
        .exclude(owner="").values_list("owner", flat=True).distinct()
    )


class ProjectListView(LoginRequiredMixin, ListView):
    template_name = "pages/project_list.html"
    context_object_name = "projects"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Project.objects.none()
        return Project.objects.filter(tenant=tenant).select_related("platform_connection")


class ProjectDetailView(LoginRequiredMixin, DetailView):
    template_name = "pages/project_detail.html"
    context_object_name = "project"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Project.objects.none()
        return Project.objects.filter(tenant=tenant).select_related("platform_connection")

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

        # Available policies for manual trigger
        context["policies"] = Policy.objects.filter(
            tenant=project.tenant, enabled=True, draft=False
        ).order_by("ordinal", "name")

        context["existing_owners"] = _existing_owners(project.tenant)

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

        stack_ids = request.POST.getlist("stacks")

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
            owner=request.POST.get("owner", ""),
        )

        if stack_ids:
            stacks = Stack.objects.filter(pk__in=stack_ids, tenant=tenant)
            project.stacks.set(stacks)

        try:
            client = get_platform_client(connection)

            # Fetch languages and topics from platform
            try:
                project.languages = client.get_languages(external_id, full_path=full_path)
                project.tags = client.get_topics(external_id, full_path=full_path)
                project.save(update_fields=["languages", "tags"])
            except Exception:
                logger.exception("Failed to fetch metadata for project %s", project.name)

            webhook_secret = secrets.token_hex(32)
            target_url = f"{settings.SITE_URL}/api/webhooks/{connection.platform}/"
            webhook_id = client.create_webhook(external_id, target_url, webhook_secret)
            project.webhook_id = webhook_id
            project.webhook_secret = webhook_secret
            project.save(update_fields=["webhook_id", "webhook_secret"])
        except Exception:
            logger.exception("Failed to register webhook for project %s", project.name)
            messages.warning(
                request,
                f'Project added but webhook registration failed. You can retry from the project page.',
            )

        messages.success(request, f'Project "{project.name}" added.')
        return redirect("project_detail", pk=project.pk)

    stacks = Stack.objects.filter(tenant=tenant).order_by("name")

    return render(
        request,
        "pages/add_project.html",
        {
            "step": "search",
            "connection": connection,
            "lifecycle_choices": Project.Lifecycle.choices,
            "stacks": stacks,
            "existing_owners": _existing_owners(tenant),
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

    if project.webhook_id:
        try:
            client = get_platform_client(project.platform_connection)
            client.delete_webhook(project.external_id, project.webhook_id)
        except Exception:
            logger.exception("Failed to delete webhook for project %s", name)

    project.delete()
    messages.success(request, f'Project "{name}" removed.')
    return redirect("project_list")


@login_required
@require_POST
def run_project_policies(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")

    project = get_object_or_404(
        Project.objects.select_related("platform_connection"),
        pk=pk,
        tenant=tenant,
    )

    policy_id = request.POST.get("policy_id")
    if policy_id:
        policies = list(
            Policy.objects.filter(pk=policy_id, tenant=tenant, enabled=True, draft=False)
        )
        if not policies:
            messages.error(request, "Policy not found or not active.")
            return redirect("project_detail", pk=pk)
    else:
        policies = None  # run_for_project will pick all eligible

    engine = PolicyEngine()
    results = engine.run_for_project(project, policies)

    if results:
        passed = sum(1 for r in results if r.get("passed"))
        messages.success(
            request,
            f"Ran {len(results)} polic{'y' if len(results) == 1 else 'ies'}: "
            f"{passed} passed, {len(results) - passed} failed.",
        )
    else:
        messages.warning(request, "No eligible policies to run.")

    return redirect("project_detail", pk=pk)


@login_required
@require_POST
def retry_webhook(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")

    project = get_object_or_404(Project, pk=pk, tenant=tenant)

    if project.webhook_id:
        try:
            client = get_platform_client(project.platform_connection)
            client.delete_webhook(project.external_id, project.webhook_id)
        except Exception:
            logger.exception("Failed to delete old webhook for project %s", project.name)

    try:
        client = get_platform_client(project.platform_connection)
        webhook_secret = secrets.token_hex(32)
        target_url = f"{settings.SITE_URL}/api/webhooks/{project.platform_connection.platform}/"
        webhook_id = client.create_webhook(project.external_id, target_url, webhook_secret)
        project.webhook_id = webhook_id
        project.webhook_secret = webhook_secret
        project.save(update_fields=["webhook_id", "webhook_secret"])
        messages.success(request, "Webhook registered successfully.")
    except Exception:
        logger.exception("Failed to register webhook for project %s", project.name)
        messages.error(request, "Webhook registration failed. Check your connection token.")

    return redirect("project_detail", pk=project.pk)


@login_required
@require_POST
def update_project_owner(request, pk):
    tenant = request.tenant
    if not tenant:
        return HttpResponseBadRequest()

    project = get_object_or_404(Project, pk=pk, tenant=tenant)

    project.owner = request.POST.get("owner", "")
    project.save(update_fields=["owner"])

    return render(request, "partials/project_owner.html", {
        "project": project,
        "existing_owners": _existing_owners(tenant),
    })
