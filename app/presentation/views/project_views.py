import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, UpdateView
from django.utils.dateparse import parse_datetime

from app.application import commit_checks, project_management
from app.application.errors import NotFoundError
from app.application.commit_checks import (
    branch_commits,
    branch_status,
    branches,
    commit_grade,
    waiting_for_commit,
)
from app.application.grading_service import (
    critical_failed_count,
    grade_for_project,
    grades_for_tenant,
)
from app.application.standard_results import breakdown, critical_summary
from app.domain.grading import tone_for
from app.domain.levels import UnknownLevel
from app.application.standard_runs import enqueue_manual_run, enqueue_run, in_flight
from app.domain.models import (
    PlatformConnection,
    Project,
    Stack,
    Standard,
    StandardExecution,
)

logger = logging.getLogger(__name__)


def _flash_runs(request, runs):
    if runs:
        messages.info(request, runs["message"])


LEVEL_FIELD = "level-"


def _posted_levels(post) -> dict:
    """The posted ``level-<standard id>`` selects, as standard id -> level."""
    return {
        key[len(LEVEL_FIELD):]: value
        for key, value in post.items()
        if key.startswith(LEVEL_FIELD)
    }


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        if not tenant:
            return context
        # One batched read for the whole list, never one per project.
        grades = grades_for_tenant(tenant)
        for project in context["projects"]:
            project_grading = grades.get(project.pk)
            project.grade = project_grading.grade if project_grading else None
        return context


def results_context(project) -> dict:
    """What the project page's Overview and Standards tabs render: the
    attached standards, the project's grade with its reason, the current
    results behind it and their breakdown, and the attachments with nothing
    to read yet."""
    context = {}
    attached_standards = list(project.standards.order_by("ordinal", "name"))
    context["attached_standards"] = attached_standards
    context["has_runnable_standards"] = any(
        s.enabled and not s.draft for s in attached_standards
    )
    context["active_standards_count"] = sum(
        1 for s in attached_standards if s.enabled and not s.draft
    )

    # Recent Activity lists only attached standards' runs
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

    # The grade and the counting result per attachment (each standard's
    # latest finished result on its home branch, GitGrit's own failures
    # skipped). Every run, on any branch and still RUNNING, shows under
    # "Recent Activity" above; only these move the grade. Attachments with
    # nothing to read yet are listed as not evaluated.
    grading = grade_for_project(project)
    context["grade"] = grading.grade
    context["grade_tone"] = tone_for(grading.grade.letter)
    context["latest_executions"] = grading.executions
    context["health_breakdown"] = breakdown(grading.executions)
    context["not_evaluated_standards"] = grading.not_evaluated
    context["critical_failed_count"] = critical_failed_count(
        grading.executions, grading.levels
    )

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
    if branch == project.default_branch:
        # The default branch shows the project grade itself, so it always
        # matches the Overview (home branches, current levels, neglect caps).
        graded = grade_for_project(project)
        status, grade = graded.executions, graded.grade
        status_critical = critical_summary(status, graded.levels)
    else:
        status = branch_status(project, branch)
        grade = commit_grade(status)
        status_critical = critical_summary(status)
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
            "status_grade": grade.letter if grade.graded else None,
            "status_tone": tone_for(grade.letter),
            "status_breakdown": breakdown(status),
            "status_critical": status_critical,
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
    run = commit_checks.run_on_branch(
        project,
        branch,
        sha=sha,
        committed_at=parse_datetime(request.POST.get("committed_at") or "") if sha else None,
        user=request.user,
    )
    notice, sha = run.notice, run.commit_sha
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
        repo = {
            "external_id": request.POST.get("external_id", "").strip(),
            "name": request.POST.get("name", "").strip(),
            "full_path": request.POST.get("full_path", "").strip(),
            "web_url": request.POST.get("web_url", "").strip(),
            "default_branch": request.POST.get("default_branch", "main").strip(),
            "description": request.POST.get("description", "").strip(),
        }
        if not repo["external_id"] or not repo["name"]:
            messages.error(request, "Please select a project.")
            return redirect("add_project_search", connection_id=connection_id)

        try:
            added = project_management.add_project(
                tenant,
                request.user,
                connection,
                repo,
                lifecycle=request.POST.get("lifecycle", Project.Lifecycle.DEVELOPMENT),
                owner=request.POST.get("owner", ""),
                stack_ids=request.POST.getlist("stacks"),
                standard_ids=request.POST.getlist("standards"),
                levels=_posted_levels(request.POST),
            )
        except project_management.AlreadyAdded:
            messages.warning(request, f'"{repo["name"]}" is already added to this workspace.')
            return redirect("project_list")
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("add_project_search", connection_id=connection_id)

        if not added.webhook_ok:
            messages.warning(
                request,
                "Project added but webhook registration failed. You can retry from the project page.",
            )
        messages.success(request, f'Project "{added.project.name}" added.')
        _flash_runs(request, added.runs)
        return redirect("project_detail", pk=added.project.pk)

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
            "standard_levels": {},
        },
    )


@login_required
def search_projects_api(request):
    """Search endpoint for HTMX — returns HTML partial or JSON."""
    tenant = request.tenant
    if not tenant:
        return JsonResponse({"results": []})

    try:
        connection = project_management.get_connection(tenant, request.GET.get("connection_id"))
    except NotFoundError:
        return JsonResponse({"results": []})

    try:
        results = project_management.search_repositories(
            tenant, connection, request.GET.get("q", "")
        )
    except project_management.PlatformError:
        if request.headers.get("HX-Request"):
            return HttpResponse(
                '<p class="text-sm text-error">Failed to search platform API. '
                "Check your connection token.</p>"
            )
        return JsonResponse({"results": [], "error": "Failed to search platform API"})

    if request.headers.get("HX-Request"):
        return render(
            request,
            "partials/project_search_results.html",
            {"results": results},
        )
    return JsonResponse({"results": results})


@login_required
@require_POST
def delete_project(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")

    try:
        name = project_management.delete_project(tenant, request.user, pk)
    except NotFoundError:
        raise Http404
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
        try:
            result = project_management.set_project_standards(
                project,
                request.POST.getlist("standards"),
                levels=_posted_levels(request.POST),
            )
        except NotFoundError:
            messages.error(request, "One of those standards no longer exists. Please try again.")
            return redirect(reverse("project_detail", args=[pk]) + "#standards")
        except UnknownLevel as exc:
            messages.error(request, str(exc))
            return redirect(reverse("project_detail", args=[pk]) + "#standards")
        standards = result["standards"]
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
        _flash_runs(request, result["runs"])
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
            "standard_levels": dict(
                project.project_standards.values_list("standard_id", "level")
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

    if project_management.register_webhook(project):
        messages.success(request, "Webhook registered successfully.")
    else:
        messages.error(request, "Webhook registration failed. Check your connection token.")

    return redirect("project_detail", pk=project.pk)


