import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from app.domain.models import Policy
from app.infrastructure.sandbox.runner import SandboxRunner

EVENT_CHOICES = ["push", "pull_request", "tag"]


class PolicyListView(LoginRequiredMixin, ListView):
    template_name = "pages/policy_list.html"
    context_object_name = "policies"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Policy.objects.none()
        return Policy.objects.filter(tenant=tenant)


class CreatePolicyView(LoginRequiredMixin, CreateView):
    template_name = "pages/policy_form.html"
    model = Policy
    fields = ["name", "description", "code", "enabled", "draft"]

    def dispatch(self, request, *args, **kwargs):
        if not request.tenant:
            messages.error(request, "No active workspace.")
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["event_choices"] = EVENT_CHOICES
        context["selected_events"] = []
        context["is_edit"] = False
        return context

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        events = self.request.POST.getlist("events")
        form.instance.criteria = {"events": events}
        test_cases_raw = self.request.POST.get("test_cases", "[]")
        try:
            form.instance.test_cases = json.loads(test_cases_raw)
        except json.JSONDecodeError:
            form.instance.test_cases = []
        self.object = form.save()
        messages.success(self.request, f'Policy "{self.object.name}" created.')
        return redirect("policy_detail", pk=self.object.pk)


class PolicyDetailView(LoginRequiredMixin, DetailView):
    template_name = "pages/policy_detail.html"
    context_object_name = "policy"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Policy.objects.none()
        return Policy.objects.filter(tenant=tenant)


class EditPolicyView(LoginRequiredMixin, UpdateView):
    template_name = "pages/policy_form.html"
    model = Policy
    fields = ["name", "description", "code", "enabled", "draft"]

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Policy.objects.none()
        return Policy.objects.filter(tenant=tenant)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["event_choices"] = EVENT_CHOICES
        criteria = self.object.criteria or {}
        context["selected_events"] = criteria.get("events", [])
        context["is_edit"] = True
        return context

    def form_valid(self, form):
        events = self.request.POST.getlist("events")
        form.instance.criteria = {"events": events}
        test_cases_raw = self.request.POST.get("test_cases", "[]")
        try:
            form.instance.test_cases = json.loads(test_cases_raw)
        except json.JSONDecodeError:
            form.instance.test_cases = []
        self.object = form.save()
        messages.success(self.request, f'Policy "{self.object.name}" updated.')
        return redirect("policy_detail", pk=self.object.pk)


@login_required
@require_POST
def delete_policy(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("policy_list")

    policy = get_object_or_404(Policy, pk=pk, tenant=tenant)
    name = policy.name
    policy.delete()
    messages.success(request, f'Policy "{name}" deleted.')
    return redirect("policy_list")


@login_required
@require_POST
def toggle_policy(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("policy_list")

    policy = get_object_or_404(Policy, pk=pk, tenant=tenant)
    policy.enabled = not policy.enabled
    policy.save(update_fields=["enabled", "updated_at"])

    if request.headers.get("HX-Request"):
        label = "Enabled" if policy.enabled else "Disabled"
        badge_class = "badge-success" if policy.enabled else "badge-ghost"
        url = reverse("toggle_policy", kwargs={"pk": policy.pk})
        return HttpResponse(
            f'<span hx-post="{url}" hx-swap="outerHTML"'
            f' class="badge {badge_class} badge-sm cursor-pointer"'
            f' title="Click to toggle">{label}</span>'
        )

    state = "enabled" if policy.enabled else "disabled"
    messages.success(request, f'Policy "{policy.name}" {state}.')
    return redirect("policy_list")


@login_required
@require_POST
def run_policy_test(request):
    """Run policy code against a test case input. Returns JSON result."""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    code = body.get("code", "")
    mock_data = body.get("input", {})

    if not code.strip():
        return JsonResponse({"error": "No policy code provided"}, status=400)

    input_config = {
        "platform": "mock",
        "project_id": "test",
        "access_token": None,
        "mock_data": mock_data,
    }

    runner = SandboxRunner()
    result = runner.run(code, input_config)
    return JsonResponse(result)
