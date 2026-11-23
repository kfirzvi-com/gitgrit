import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView

from app.application import stack_service
from app.application.stack_health import StackHealth
from app.application.dependency_agent import refresh_stack_map
from app.domain.models import Project, Stack
from app.presentation.smart_table import StackRow
from app.presentation.architecture import stack_graph
from app.presentation.health_note import HealthNote


class StackListView(LoginRequiredMixin, ListView):
    template_name = "pages/stack_list.html"
    context_object_name = "stacks"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Stack.objects.none()
        return (
            Stack.objects.filter(tenant=tenant).prefetch_related("projects")
        )

    def get_context_data(self, **kwargs):
        """A row per stack (``StackRow``): its projects counted by health
        (``ProjectHealthCounts``), never one grade or colour for the stack,
        and their owners; the page's smart table sorts and groups them."""
        context = super().get_context_data(**kwargs)
        context["rows"] = StackRow.for_stacks(context["stacks"])
        return context


class CreateStackView(LoginRequiredMixin, CreateView):
    template_name = "pages/create_stack.html"
    model = Stack
    fields = ["name", "description"]

    def dispatch(self, request, *args, **kwargs):
        if not request.tenant:
            messages.error(request, "No active workspace.")
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = stack_service.create_stack(
            tenant=self.request.tenant,
            name=form.cleaned_data["name"],
            description=form.cleaned_data.get("description", ""),
        )
        messages.success(self.request, f'Stack "{self.object.name}" created.')
        return redirect("stack_detail", pk=self.object.pk)


class StackDetailView(LoginRequiredMixin, DetailView):
    template_name = "pages/stack_detail.html"
    context_object_name = "stack"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Stack.objects.none()
        return Stack.objects.filter(tenant=tenant)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stack = self.object
        view = StackHealth.of(stack)
        projects = []
        for row in view.projects:
            project = row.project
            project.tone, project.score = row.tone, row.score
            project.health_note = HealthNote.text(row.score)
            projects.append(project)
        context.update(
            stack_projects=projects,
            project_count=view.project_count,
            standard_count=view.standard_count,
            stack_health=view.health,
            map_updated_at=view.map_updated_at,
            map_analyzing=view.map_refreshing,
            architecture_data=json.dumps(stack_graph(stack)),
        )
        return context


@login_required
@require_POST
def refresh_stack(request, pk):
    """Rebuild the stack's map from its projects' main branches (queued; the
    worker does the reading). Superusers only: it costs one LLM run per
    project."""
    if not request.user.is_superuser:
        raise PermissionDenied
    stack = get_object_or_404(Stack, pk=pk, tenant=request.tenant)
    queued = refresh_stack_map(stack)
    if queued:
        messages.success(
            request,
            f"Refreshing the map from the main branch of {queued} "
            f"project{'' if queued == 1 else 's'}. It updates as each one finishes.",
        )
    else:
        messages.warning(request, "No projects to refresh.")
    return redirect("stack_detail", pk=pk)


@login_required
@require_POST
def delete_stack(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=pk, tenant=tenant)
    name = stack.name
    stack_service.delete_stack(stack=stack)
    messages.success(request, f'Stack "{name}" deleted.')
    return redirect("stack_list")


@login_required
@require_POST
def edit_stack(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=pk, tenant=tenant)
    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, "Stack name cannot be empty.")
        return redirect("stack_detail", pk=pk)

    stack_service.update_stack(
        stack=stack,
        name=name,
        description=request.POST.get("description", "").strip(),
    )
    messages.success(request, f'Stack "{stack.name}" updated.')
    return redirect("stack_detail", pk=pk)


@login_required
def stack_projects(request, pk):
    """Manage which workspace projects belong to a stack.

    GET returns the searchable picker partial (for the HTMX modal on the
    stack page); POST replaces the membership set and redirects back.
    """
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=pk, tenant=tenant)

    if request.method == "POST":
        project_ids = request.POST.getlist("projects")
        projects = list(Project.objects.filter(pk__in=project_ids, tenant=tenant))
        added, removed = stack_service.set_stack_projects(tenant=tenant, stack=stack, projects=projects)
        parts = []
        if added:
            parts.append(f"{added} project{'' if added == 1 else 's'} added")
        if removed:
            parts.append(f"{removed} project{'' if removed == 1 else 's'} removed")
        if parts:
            messages.success(request, f'{" and ".join(parts)} in "{stack.name}".')
        return redirect("stack_detail", pk=pk)

    if not request.headers.get("HX-Request"):
        return redirect("stack_detail", pk=pk)

    return render(
        request,
        "partials/stack_projects_form.html",
        {
            "stack": stack,
            "workspace_projects": Project.objects.filter(tenant=tenant).order_by("name"),
            "member_project_ids": set(
                Project.objects.filter(tenant=tenant, stacks=stack).values_list("pk", flat=True)
            ),
        },
    )


@login_required
@require_POST
def remove_project_from_stack(request, stack_pk, project_pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=stack_pk, tenant=tenant)
    project = get_object_or_404(Project, pk=project_pk, tenant=tenant)
    stack_service.remove_project_from_stack(tenant=tenant, stack=stack, project=project)
    messages.success(request, f'Removed "{project.name}" from "{stack.name}".')
    return redirect("stack_detail", pk=stack_pk)
