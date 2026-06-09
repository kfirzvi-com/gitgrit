import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView

from app.domain.models import Project, ProjectStack, Stack
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
        form.instance.tenant = self.request.tenant
        self.object = form.save()
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
        context["available_projects"] = (
            Project.objects.filter(tenant=stack.tenant)
            .exclude(stacks=stack)
            .order_by("name")
        )
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
def add_project_to_stack(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=pk, tenant=tenant)
    project_id = request.POST.get("project_id")
    if not project_id:
        messages.error(request, "No project selected.")
        return redirect("stack_detail", pk=pk)

    project = get_object_or_404(Project, pk=project_id, tenant=tenant)
    ProjectStack.objects.get_or_create(project=project, stack=stack)
    messages.success(request, f'Added "{project.name}" to "{stack.name}".')
    return redirect("stack_detail", pk=pk)


@login_required
@require_POST
def remove_project_from_stack(request, stack_pk, project_pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=stack_pk, tenant=tenant)
    project = get_object_or_404(Project, pk=project_pk, tenant=tenant)
    ProjectStack.objects.filter(project=project, stack=stack).delete()
    messages.success(request, f'Removed "{project.name}" from "{stack.name}".')
    return redirect("stack_detail", pk=stack_pk)
