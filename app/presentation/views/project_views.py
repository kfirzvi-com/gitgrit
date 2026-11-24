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

from app.presentation.project_overview import ProjectOverview
from app.presentation.bulk_edit_answer import BulkEditAnswer
from app.application.delivery import DeliveryReport, DeliverySyncRequest
from app.application.project_bulk_edit import ProjectBulkEdit
from app.application.project_suggestions import ProjectSuggestions
from app.presentation.htmx import toast
from app.application import commit_checks, project_management
from app.application.errors import NotFoundError
from app.application.commit_checks import (
    branch_commits,
    branches,
    waiting_for_commit,
)
from app.application import scoring
from app.domain.scoring import CommitScoreOutcome
from app.presentation.commit_results import CommitResultGrouping
from app.presentation.smart_table import ProjectRow
from app.application.standard_results import outcome_counts
from app.application.standard_runs import enqueue_manual_run, enqueue_run, in_flight
from app.domain import importance, schedules
from app.presentation.schedule_chip import ScheduleChip
from app.presentation import importance_text
from app.domain.models import (
    DeliverySettings,
    Platform,
    PlatformConnection,
    Project,
    ProjectStandard,
    Stack,
    Standard,
    StandardExecution,
)

logger = logging.getLogger(__name__)


def _flash_runs(request, runs):
    if runs:
        messages.info(request, runs["message"])


IMPORTANCE_FIELD = "importance-"
TRIGGER_FIELD = "trigger-"
SCHEDULE_FIELD = "schedule-"
SCHEDULE_TIME_ZONE_FIELD = "schedule_tz-"


def _posted_importances(post) -> dict:
    """The standards table's ``importance-<standard id>`` choices, as
    standard id -> posted value."""
    return {
        key[len(IMPORTANCE_FIELD):]: value
        for key, value in post.items()
        if key.startswith(IMPORTANCE_FIELD)
    }


def _posted_schedules(post) -> dict:
    """The standards table's ``trigger-``, ``schedule-`` and
    ``schedule_tz-<standard id>`` fields, as standard id -> (trigger, cron
    text, time zone)."""
    return {
        key[len(TRIGGER_FIELD):]: (
            value,
            post.get(SCHEDULE_FIELD + key[len(TRIGGER_FIELD):], ""),
            post.get(SCHEDULE_TIME_ZONE_FIELD + key[len(TRIGGER_FIELD):], ""),
        )
        for key, value in post.items()
        if key.startswith(TRIGGER_FIELD)
    }


def _picker_context(tenant, project=None, user=None) -> dict:
    """What the standards table needs: the workspace's standards, which are
    attached, and each attached standard's importance and what runs it."""
    attachments = list(
        ProjectStandard.objects.filter(project=project) if project else ProjectStandard.objects.none()
    )
    by_standard = {a.standard_id: a for a in attachments}
    # A new schedule starts in the zone on the viewer's profile, when they
    # set one; else the editor starts from their browser's.
    viewer_time_zone = (user.time_zone or "") if user and user.is_authenticated else ""
    standards = list(
        Standard.objects.filter(tenant=tenant).prefetch_related("labels").order_by("ordinal", "name")
    )
    for standard in standards:
        attachment = by_standard.get(standard.pk)
        # The row's importance: the attached standard's, else what attaching
        # it would start at.
        standard.importance = attachment.importance if attachment else importance.DEFAULT.value
        standard.schedule_chip = ScheduleChip.of(
            attachment.standard_schedule if attachment else schedules.StandardSchedule(), viewer_time_zone
        )
    return {
        "workspace_standards": standards,
        "attached_standard_ids": set(by_standard),
        "importance_options": importance_text.options(),
        "trigger_options": ScheduleChip.trigger_options(),
        "viewer_time_zone": viewer_time_zone,
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
        return (
            Project.objects.filter(tenant=tenant)
            .select_related("platform_connection")
            .prefetch_related("stacks")
        )

    def get_context_data(self, **kwargs):
        """A row per project (``ProjectRow``): its newest commit's grade, or
        why there is none, its health and its stacks; the page's smart table
        sorts and groups them in place."""
        context = super().get_context_data(**kwargs)
        context["rows"] = ProjectRow.for_projects(context["projects"])
        # The bulk bar's menus.
        tenant = self.request.tenant
        context["owners"] = sorted(_existing_owners(tenant), key=str.lower) if tenant else []
        context["lifecycle_choices"] = Project.Lifecycle.choices
        context["stacks"] = Stack.objects.filter(tenant=tenant) if tenant else []
        context["standards"] = Standard.objects.filter(tenant=tenant).order_by("name") if tenant else []
        context["importance_options"] = importance_text.options()
        return context


def results_context(project) -> dict:
    """What the project page's Overview and Standards tabs render: the
    attached standards, the project's score (its newest scored commit on the
    default branch's newest commit, whatever its outcome) with the results
    behind it and their breakdown."""
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

    # The project's score: its default branch's newest commit, and the
    # results it was decided from. Every run, on any branch and still
    # RUNNING, shows under "Recent Activity" above.
    head = scoring.branch_head(project, project.default_branch)
    score = head.score if head else None
    latest_executions = list(score.executions.order_by("-created_at")) if score else []
    context["branch_head"] = head
    context["project_score"] = score
    context["latest_executions"] = latest_executions
    context["compliance_score"] = score.value if score else None
    # A verdict to show: failed (no number) or scored.
    context["project_has_score"] = _has_verdict(score)
    context["health_breakdown"] = outcome_counts(latest_executions)

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
        """The Overview summarises every tab: the score and its results, and
        for a Git project its delivery (a first visit starts its first sync)."""
        context = super().get_context_data(**kwargs)
        project = self.object
        context.update(results_context(project))
        delivery = None
        if not project.is_artifact:
            settings, _ = DeliverySettings.objects.get_or_create(project=project)
            if settings.refreshed_at is None and settings.refresh_requested_at is None:
                DeliverySyncRequest.send(project)
            delivery = DeliveryReport.for_project(project)
        context["delivery"] = delivery
        context["overview"] = ProjectOverview(project, context, delivery)
        return context


def _has_verdict(score) -> bool:
    """A commit score to show as a grade: failed (no number) or scored
    (``scoring.CommitScoreOutcome.is_verdict``)."""
    return score is not None and score.outcome.is_verdict


def _history(request, project, branch, page=1, notice="", open_sha=""):
    branch_names = branches(project)
    if branch not in branch_names:
        branch_names.append(branch)
    rows, has_more = branch_commits(project, branch, page)
    for row in rows:
        row.result_groups = CommitResultGrouping.of(row.selected.latest_runs if row.selected else [])
    # The branch's score: its newest commit's, and the results behind it.
    head = scoring.branch_head(project, branch)
    score = head.score if head else None
    status = list(score.executions.select_related("commit_check")) if score else []
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
            "status_score": score.value if score else None,
            "status_has_score": _has_verdict(score),
            "branch_score": score,
            "status_breakdown": outcome_counts(status),
            "branch_head": head,
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
def project_commit_check(request, pk, check_id):
    """One run of the standards on a commit, picked on the Results tab's
    timeline: the timeline with that run selected and its results, swapped
    in place of the commit's open body."""
    project = get_object_or_404(Project, pk=pk, tenant=request.tenant)
    row = commit_checks.commit_runs(project, check_id)
    if row is None:
        raise Http404("No such check")
    row.result_groups = CommitResultGrouping.of(row.selected.latest_runs)
    return render(
        request,
        "partials/commit_check_runs.html",
        {"project": project, "row": row, "branch": row.branch, "page": _page(request.GET.get("page"))},
    )


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

    # Artifact projects are created through the API, never picked from a list.
    connections = (
        PlatformConnection.objects.filter(tenant=tenant)
        .exclude(platform=Platform.ARTIFACT)
        .order_by("created_at")
    )
    # Uploading a build needs no connection, so the page always has a choice.
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
                root_path=request.POST.get("root_path", ""),
                lifecycle=request.POST.get("lifecycle", Project.Lifecycle.DEVELOPMENT),
                owner=request.POST.get("owner", ""),
                stack_ids=request.POST.getlist("stacks"),
                standard_ids=request.POST.getlist("standards"),
                importances=_posted_importances(request.POST),
            )
        except project_management.AlreadyAdded as exc:
            messages.warning(request, str(exc))
            return redirect("project_detail", pk=exc.project.pk)
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
            **_picker_context(tenant),
        },
    )


@login_required
def root_path_options(request, connection_id):
    """The directories a project of the chosen repository could be rooted
    at, for the add-project form's root-path autocomplete (JSON)."""
    tenant = request.tenant
    connection = get_object_or_404(PlatformConnection, id=connection_id, tenant=tenant)
    repo = {
        "external_id": request.GET.get("external_id", ""),
        "full_path": request.GET.get("full_path", ""),
        "default_branch": request.GET.get("default_branch", ""),
    }
    if not repo["full_path"]:
        return JsonResponse({"options": []})
    options = project_management.root_path_options(tenant, connection, repo)
    return JsonResponse(
        {"options": [{"path": o.path, "manifests": list(o.manifests)} for o in options]}
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
                importances=_posted_importances(request.POST),
                schedules=_posted_schedules(request.POST),
            )
        except NotFoundError:
            messages.error(request, "One of those standards no longer exists. Please try again.")
            return redirect(reverse("project_detail", args=[pk]) + "#standards")
        except (importance.UnknownImportance, schedules.InvalidSchedule) as exc:
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
            **_picker_context(tenant, project, request.user),
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
    if project.is_artifact:
        messages.error(request, "Artifact projects receive no webhooks.")
        return redirect("project_detail", pk=project.pk)

    if project_management.register_webhook(project):
        messages.success(request, "Webhook registered successfully.")
    else:
        messages.error(request, "Webhook registration failed. Check your connection token.")

    return redirect("project_detail", pk=project.pk)


@login_required
@require_POST
def add_suggested_projects(request, pk):
    """Add one suggested project (``path``) or, without one, every open
    suggestion of this whole-repository project. Answers HTMX with the
    repository section swapped in place."""
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")
    project = get_object_or_404(Project.objects.select_related("platform_connection"), pk=pk, tenant=tenant)
    path = request.POST.get("path")
    result = ProjectSuggestions(project, request.user).add([path] if path else None)
    if result.added:
        names = ", ".join(p.name for p in result.added)
        text = f"Added {names}." if len(result.added) <= 3 else f"Added {len(result.added)} projects."
        level = "success"
    else:
        text, level = "Nothing to add: those are projects already.", "info"
    if not request.headers.get("HX-Request"):
        getattr(messages, level)(request, text)
        return redirect("project_detail", pk=project.pk)
    response = render(request, "partials/project_repository.html", {"project": project})
    return toast(response, text, level)


@login_required
@require_POST
def bulk_edit_projects(request):
    """The Projects page's bulk bar: owner, lifecycle, stack, or attach or
    detach a standard on the selected projects (``ProjectBulkEdit``)."""
    return BulkEditAnswer.to(request, ProjectBulkEdit, importance_value=request.POST.get("importance", ""))
