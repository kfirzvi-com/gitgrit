import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView

from app.application import stack_service
from app.domain.models import Project, Stack
from app.presentation.architecture import latest_scores_by_project, stack_graph


class StackListView(LoginRequiredMixin, ListView):
    template_name = "pages/stack_list.html"
    context_object_name = "stacks"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Stack.objects.none()
        return (
            Stack.objects.filter(tenant=tenant)
            .annotate(project_count=Count("projects"))
        )


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
        stack_projects = Project.objects.filter(
            tenant=stack.tenant, stacks=stack
        ).select_related("platform_connection")
        context["stack_projects"] = stack_projects
        latest = latest_scores_by_project(stack.tenant)
        context["architecture_data"] = json.dumps(stack_graph(stack, latest))
        return context


@login_required
@require_POST
def delete_stack(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=pk, tenant=tenant)
    name = stack.name
    stack.delete()
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
        added, removed = stack_service.set_stack_projects(
            tenant=tenant, stack=stack, projects=projects
        )
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
                Project.objects.filter(tenant=tenant, stacks=stack).values_list(
                    "pk", flat=True
                )
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
