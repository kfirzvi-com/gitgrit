import logging
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, UpdateView

from app.application.event_bus import publish
from app.application.standard_engine import StandardEngine
from app.domain.events import ProjectCreated, ProjectDeleted, StandardsAttached
from app.domain.models import (
    AuthMethod,
    PlatformConnection,
    Project,
    Stack,
    Standard,
    StandardExecution,
)
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger(__name__)


def _run_newly_attached(request, project, standards, previously_attached_ids):
    """Publish the attach delta — newly attached, runnable standards run on
    the project immediately — and flash the run summary."""
    newly_runnable = [
        s
        for s in standards
        if s.pk not in previously_attached_ids and s.enabled and not s.draft
    ]
    if not newly_runnable:
        return
    results = publish(
        StandardsAttached(
            project_id=str(project.pk),
            tenant_id=str(project.tenant_id),
            standard_ids=tuple(str(s.pk) for s in newly_runnable),
        )
    )
    if results:
        messages.info(request, results[0]["message"])


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

        attached_standards = list(project.standards.order_by("ordinal", "name"))
        context["attached_standards"] = attached_standards
        context["has_runnable_standards"] = any(
            s.enabled and not s.draft for s in attached_standards
        )
        context["active_standards_count"] = sum(
            1 for s in attached_standards if s.enabled and not s.draft
        )

        # Executions of detached standards must not drag the score
        recent_executions = StandardExecution.objects.filter(
            project=project,
            standard__in=attached_standards,
        ).select_related("standard")[:50]
        context["recent_executions"] = recent_executions

        # Deduplicate: latest execution per standard
        seen_standards = {}
        for ex in recent_executions:
            if ex.standard_id not in seen_standards:
                seen_standards[ex.standard_id] = ex
        latest_executions = list(seen_standards.values())
        context["latest_executions"] = latest_executions

        # Compliance score: average of latest-per-standard scores
        if latest_executions:
            context["compliance_score"] = round(
                sum(ex.score for ex in latest_executions) / len(latest_executions)
            )
        else:
            context["compliance_score"] = None

        return context


class EditProjectView(LoginRequiredMixin, UpdateView):
    template_name = "pages/project_form.html"
    model = Project
    fields = ["lifecycle", "owner"]

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Project.objects.none()
        return Project.objects.filter(tenant=tenant)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["lifecycle_choices"] = Project.Lifecycle.choices
        context["existing_owners"] = _existing_owners(self.request.tenant)
        return context

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Project "{self.object.name}" updated.')
        return redirect("project_detail", pk=self.object.pk)


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
        standard_ids = request.POST.getlist("standards")

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

        attached_standards = []
        if standard_ids:
            attached_standards = list(
                Standard.objects.filter(pk__in=standard_ids, tenant=tenant)
            )
            project.standards.set(attached_standards)

        try:
            client = get_platform_client(connection)

            # Fetch languages and topics from platform
            try:
                project.languages = client.get_languages(external_id, full_path=full_path)
                project.tags = client.get_topics(external_id, full_path=full_path)
                project.save(update_fields=["languages", "tags"])
            except Exception:
                logger.exception("Failed to fetch metadata for project %s", project.name)

            # GitHub App connections receive events through the App's own
            # webhook (configured once on the App), so no per-repo hook is
            # created. PAT connections still register a per-repo webhook.
            if connection.auth_method != AuthMethod.GITHUB_APP:
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

        publish(ProjectCreated(project_id=str(project.id), tenant_id=str(tenant.id)))
        messages.success(request, f'Project "{project.name}" added.')
        # After the metadata fetch above, so language criteria see real data.
        _run_newly_attached(
            request, project, attached_standards, previously_attached_ids=set()
        )
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
            "workspace_standards": Standard.objects.filter(tenant=tenant)
            .prefetch_related("labels")
            .order_by("ordinal", "name"),
            "attached_standard_ids": set(),
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

    project_id = str(project.pk)
    project.delete()
    publish(ProjectDeleted(project_id=project_id, tenant_id=str(tenant.id)))
    messages.success(request, f'Project "{name}" removed.')
    return redirect("project_list")


@login_required
@require_POST
def run_project_standards(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")

    project = get_object_or_404(
        Project.objects.select_related("platform_connection"),
        pk=pk,
        tenant=tenant,
    )

    standard_id = request.POST.get("standard_id")
    if standard_id:
        standards = list(
            Standard.objects.filter(
                pk=standard_id,
                tenant=tenant,
                enabled=True,
                draft=False,
                projects=project,
            )
        )
        if not standards:
            messages.error(request, "Standard not found or not active.")
            return redirect("project_detail", pk=pk)
    else:
        standards = None  # run_for_project will pick all eligible

    engine = StandardEngine()
    results = engine.run_for_project(project, standards)

    if results:
        passed = sum(1 for r in results if r.get("passed"))
        messages.success(
            request,
            f"Ran {len(results)} standard{'' if len(results) == 1 else 's'}: "
            f"{passed} passed, {len(results) - passed} failed.",
        )
    else:
        messages.warning(request, "No eligible standards to run.")

    # On a run-all, report anything attached that was skipped, and why —
    # silent skips read as "everything ran" (single-standard runs already
    # error out above when the standard isn't eligible).
    if standards is None:
        ran_ids = {r["standard_id"] for r in results}
        skipped = [
            s for s in project.standards.all() if str(s.id) not in ran_ids
        ]
        if skipped:
            draft_count = sum(1 for s in skipped if s.draft)
            disabled_count = sum(1 for s in skipped if not s.enabled and not s.draft)
            criteria_count = len(skipped) - draft_count - disabled_count
            parts = []
            if disabled_count:
                parts.append(f"{disabled_count} disabled")
            if draft_count:
                parts.append(f"{draft_count} draft{'' if draft_count == 1 else 's'}")
            if criteria_count:
                parts.append(f"{criteria_count} language/criteria mismatch")
            messages.warning(
                request,
                f"Skipped {len(skipped)} standard{'' if len(skipped) == 1 else 's'}: "
                f"{', '.join(parts)}.",
            )

    return redirect("project_detail", pk=pk)


@login_required
def project_standards(request, pk):
    """Manage which workspace standards are attached to a project.

    GET returns the searchable picker partial (for the HTMX modal on the
    project page); POST replaces the attachment set and redirects back.
    """
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")

    project = get_object_or_404(Project, pk=pk, tenant=tenant)

    if request.method == "POST":
        standard_ids = request.POST.getlist("standards")
        standards = list(Standard.objects.filter(pk__in=standard_ids, tenant=tenant))
        previously_attached_ids = set(
            project.standards.values_list("pk", flat=True)
        )
        project.standards.set(standards)
        count = len(standards)
        if count:
            messages.success(
                request,
                f"{count} standard{'' if count == 1 else 's'} attached to \"{project.name}\".",
            )
            draft_count = sum(1 for s in standards if s.draft)
            disabled_count = sum(1 for s in standards if not s.enabled and not s.draft)
            if draft_count or disabled_count:
                parts = []
                if draft_count:
                    parts.append(f"{draft_count} draft{'' if draft_count == 1 else 's'}")
                if disabled_count:
                    parts.append(f"{disabled_count} disabled")
                total_inactive = draft_count + disabled_count
                reminder = (
                    "This standard will not run during checks."
                    if total_inactive == 1
                    else "These standards will not run during checks."
                )
                messages.warning(
                    request,
                    f"Among the selected standards: {' and '.join(parts)}. {reminder}",
                )
        else:
            messages.success(request, f'All standards detached from "{project.name}".')
        _run_newly_attached(request, project, standards, previously_attached_ids)
        return redirect("project_detail", pk=pk)

    if not request.headers.get("HX-Request"):
        return redirect("project_detail", pk=pk)

    return render(
        request,
        "partials/project_standards_form.html",
        {
            "project": project,
            "workspace_standards": Standard.objects.filter(tenant=tenant)
            .prefetch_related("labels")
            .order_by("ordinal", "name"),
            "attached_standard_ids": set(
                project.standards.values_list("pk", flat=True)
            ),
        },
    )


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


