import logging
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, UpdateView
from django.utils.dateparse import parse_datetime

from app.application import stack_service
from app.application.event_bus import publish
from app.application.commit_checks import (
    branch_commits,
    branch_status,
    branches,
    resolve_head_commit,
    waiting_for_commit,
)
from app.application.standard_engine import StandardEngine
from app.application.standard_results import breakdown, current_results, project_score
from app.application.standard_runs import enqueue_manual_run, enqueue_run, in_flight
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
    """Publish the attach delta — newly attached, runnable standards are queued
    to run on the project — and flash the enqueue summary."""
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


def results_context(project) -> dict:
    """What the project page's Overview and Standards tabs render: the
    attached standards, the project's current results, its health score and
    that score's breakdown."""
    context = {}
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

    # In-flight runs: keep polling while any exists, and mark those standards.
    # A RUNNING row past the stale cutoff is not in flight — the worker lost
    # it — so it neither polls nor disables Run (the sweep will ERROR it).
    context["running_standard_ids"] = set(
        in_flight(
            StandardExecution.objects.filter(
                project=project, standard__in=attached_standards
            )
        ).values_list("standard_id", flat=True)
    )

    # Each standard's current result on its home branch. Every run, on any
    # branch and still RUNNING, shows under "Recent Activity" above; only
    # these move the score.
    latest_executions = sorted(
        current_results([project]), key=lambda ex: ex.created_at, reverse=True
    )
    context["latest_executions"] = latest_executions
    context["compliance_score"] = project_score(latest_executions)
    context["health_breakdown"] = breakdown(latest_executions)

    return context


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
        context.update(results_context(self.object))
        return context


def _history(request, project, branch, page=1, notice="", open_sha=""):
    branch_names = branches(project)
    if branch not in branch_names:
        branch_names.append(branch)
    rows, has_more = branch_commits(project, branch, page)
    status = branch_status(project, branch)
    # The score's results can come from several commits (a standard that did
    # not run on the newest one keeps its earlier result); the header says so.
    status_commits = list(dict.fromkeys(
        ex.commit_check.commit_sha[:7] for ex in status if ex.commit_check and ex.commit_check.commit_sha
    ))
    # The commit that starts open: the one just run, else the newest checked.
    if not open_sha and page == 1:
        open_sha = next((row.sha for row in rows if row.checked), "")
    return render(
        request,
        "partials/project_history.html",
        {
            "project": project,
            "branches": branch_names,
            "branch": branch,
            "is_default": branch == project.default_branch,
            "rows": rows,
            "page": page,
            "has_more": has_more,
            "status": status,
            "status_score": project_score(status),
            "status_breakdown": breakdown(status),
            "status_commits": status_commits,
            "open_sha": open_sha,
            "running": any(row.running for row in rows) or waiting_for_commit(project, branch),
            "notice": notice,
        },
    )


def _page(value) -> int:
    try:
        return max(1, int(value or 1))
    except ValueError:
        return 1


@login_required
def project_history(request, pk):
    """The project page's Health card: a branch picker (the default branch
    first), that branch's results, and its commits, each with the standards
    GitGrit ran on it. Loaded after the page, since it asks the Git platform
    for the branches and commits."""
    project = get_object_or_404(Project, pk=pk, tenant=request.tenant)
    branch = request.GET.get("branch") or project.default_branch
    return _history(request, project, branch, _page(request.GET.get("page")))


@login_required
@require_POST
def run_on_branch(request, pk):
    """Run the project's current standards that apply to a branch: on the
    branch's latest commit, or on one commit (``sha``). Answers with the
    refreshed Results tab, which then follows the run."""
    project = get_object_or_404(Project, pk=pk, tenant=request.tenant)
    branch = request.POST.get("branch") or project.default_branch
    sha = request.POST.get("sha", "")
    committed_at = parse_datetime(request.POST.get("committed_at") or "") if sha else None
    target = sha[:7] if sha else f"the latest commit on {branch}"
    if not sha:
        # Pin the run to the branch's head now, so its commit shows it
        # running at once. If the platform cannot say, the job pins it.
        head = resolve_head_commit(project, branch)
        sha = head.get("sha", "")
        committed_at = parse_datetime(head["date"]) if head.get("date") else None
        if sha:
            target = f"{sha[:7]}, the latest commit on {branch}"
    standards = StandardEngine().standards_for_branch(project, branch)
    summary = enqueue_run(
        project,
        standards,
        triggered_by="manual",
        user=request.user,
        ref=branch,
        commit_sha=sha,
        committed_at=committed_at,
    )
    if summary is None:
        notice = f"No standards apply to {branch}."
    elif summary["queued"]:
        notice = f"Running {summary['queued']} standard{'s' if summary['queued'] != 1 else ''} on {target}."
    else:
        notice = "Those standards are already running."
    return _history(request, project, branch, _page(request.POST.get("page")), notice=notice, open_sha=sha)


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
            stack_service.add_project_to_stacks(tenant=tenant, project=project, stacks=stacks)

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

        publish(
            ProjectCreated(
                project_id=str(project.id), tenant_id=str(tenant.id), user_id=str(request.user.pk)
            )
        )
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
    publish(
        ProjectDeleted(
            project_id=project_id,
            tenant_id=str(tenant.id),
            project_name=name,
            user_id=str(request.user.pk),
        )
    )
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
    run_all = not standard_id
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
        # Run one: the user picked it, so the language/criteria filter that
        # Run All applies is skipped — only attached + active is required.
        summary = enqueue_run(project, standards, user=request.user)
    else:
        standards = list(project.standards.all())
        summary = enqueue_manual_run(project, standards, user=request.user)

    if summary:
        messages.success(request, summary["message"])
    else:
        messages.warning(request, "No eligible standards to run.")

    # On a run-all, report anything attached that was skipped, and why —
    # silent skips read as "everything ran" (single-standard runs already
    # error out above when the standard isn't eligible).
    if run_all:
        queued_ids = {e["standard_id"] for e in (summary or {}).get("executions", [])}
        running_ids = {
            str(sid)
            for sid in in_flight(
                StandardExecution.objects.filter(project=project, standard__in=standards)
            ).values_list("standard_id", flat=True)
        }
        skipped = [
            s for s in standards if str(s.id) not in queued_ids | running_ids
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

    GET returns the searchable picker partial, embedded in the project page's
    Standards tab; POST replaces the attachment set and returns to that tab.
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
        return redirect(reverse("project_detail", args=[pk]) + "#standards")

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


