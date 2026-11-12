import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView

from app.application import stack_service
from app.application.dependency_agent import refresh_stack_map
from app.domain.models import Component, Stack, Standard
from app.domain.score_representation import ScoreTone
from app.application.project_health_counts import ProjectHealthCounts
from app.presentation.architecture import map_status, stack_graph
from app.presentation.health_note import HealthNote


class StackListView(LoginRequiredMixin, ListView):
    template_name = "pages/stack_list.html"
    context_object_name = "stacks"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Stack.objects.none()
        return (
            Stack.objects.filter(tenant=tenant)
            .annotate(component_count=Count("components"))
            .prefetch_related("components__project")
        )

    def get_context_data(self, **kwargs):
        """Each stack with its projects counted by health
        (``ProjectHealthCounts``): never one grade or colour for the stack."""
        context = super().get_context_data(**kwargs)
        stacks = list(context["stacks"])
        health = ProjectHealthCounts.for_stacks(stacks)
        for stack in stacks:
            stack.project_health = health[stack.pk]
        context["stacks"] = stacks
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
        components = list(
            Component.objects.filter(tenant=stack.tenant, stacks=stack).select_related(
                "project", "project__platform_connection"
            )
        )
        projects = list({c.project_id: c.project for c in components}.values())
        health = ProjectHealthCounts.of(projects)

        # Each component shows its repository's health and grade; worst first.
        health_of = {
            project.pk: (tone, score)
            for tone in (ScoreTone.FAILED, ScoreTone.NEEDS_ATTENTION, ScoreTone.HEALTHY)
            for project, score in health.projects_with(tone)
        }
        for component in components:
            component.tone, component.score = health_of.get(component.project_id, (ScoreTone.UNKNOWN, None))
            component.health_note = HealthNote.text(component.score)
        components.sort(key=lambda c: (-c.tone.severity, c.name.lower()))

        status = map_status(stack.projects)
        context.update(
            stack_components=components,
            project_count=len(projects),
            standard_count=Standard.objects.filter(
                tenant=stack.tenant, enabled=True, projects__in=projects
            ).distinct().count(),
            stack_health=health,
            map_updated_at=status["updated_at"],
            map_analyzing=status["analyzing"],
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
def stack_components(request, pk):
    """Manage which workspace components belong to a stack.

    GET returns the searchable picker partial (for the HTMX modal on the
    stack page); POST replaces the membership set and redirects back.
    """
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=pk, tenant=tenant)

    if request.method == "POST":
        component_ids = request.POST.getlist("components")
        components = list(Component.objects.filter(pk__in=component_ids, tenant=tenant))
        added, removed = stack_service.set_stack_components(
            tenant=tenant, stack=stack, components=components
        )
        parts = []
        if added:
            parts.append(f"{added} component{'' if added == 1 else 's'} added")
        if removed:
            parts.append(f"{removed} component{'' if removed == 1 else 's'} removed")
        if parts:
            messages.success(request, f'{" and ".join(parts)} in "{stack.name}".')
        return redirect("stack_detail", pk=pk)

    if not request.headers.get("HX-Request"):
        return redirect("stack_detail", pk=pk)

    return render(
        request,
        "partials/stack_components_form.html",
        {
            "stack": stack,
            "workspace_components": Component.objects.filter(tenant=tenant)
            .select_related("project")
            .order_by("project__name", "path"),
            "member_component_ids": set(
                Component.objects.filter(tenant=tenant, stacks=stack).values_list(
                    "pk", flat=True
                )
            ),
        },
    )


@login_required
@require_POST
def remove_component_from_stack(request, stack_pk, component_pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("stack_list")

    stack = get_object_or_404(Stack, pk=stack_pk, tenant=tenant)
    component = get_object_or_404(
        Component.objects.select_related("project"), pk=component_pk, tenant=tenant
    )
    stack_service.remove_component_from_stack(tenant=tenant, stack=stack, component=component)
    messages.success(request, f'Removed "{component.name}" from "{stack.name}".')
    return redirect("stack_detail", pk=stack_pk)
