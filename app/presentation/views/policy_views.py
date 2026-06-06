import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from app.application.policy_service import create_policy_version
from app.domain.models import Policy, PolicyLabel, PolicyVersion
from app.domain.policy_validator import validate_policy_code
from app.infrastructure.sandbox.runner import SandboxRunner

EVENT_CHOICES = ["push", "pull_request", "tag"]
LANGUAGE_CHOICES = [
    "python", "javascript", "typescript", "go", "java", "ruby",
    "rust", "c", "c++", "c#", "php", "swift", "kotlin", "scala",
]


class PolicyListView(LoginRequiredMixin, ListView):
    template_name = "pages/policy_list.html"
    context_object_name = "policies"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Policy.objects.none()
        return (
            Policy.objects.filter(tenant=tenant)
            .prefetch_related("labels")
            .select_related("source_marketplace_policy")
        )


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
        context["language_choices"] = LANGUAGE_CHOICES
        context["tenant_labels"] = PolicyLabel.objects.filter(tenant=self.request.tenant)
        context["selected_events"] = []
        context["selected_languages"] = []
        context["selected_label_ids"] = []
        context["ref_pattern"] = ""
        context["is_edit"] = False
        return context

    def form_valid(self, form):
        try:
            validate_policy_code(form.cleaned_data.get("code", ""))
        except ValueError as e:
            form.add_error("code", str(e))
            return self.form_invalid(form)
        form.instance.tenant = self.request.tenant
        events = self.request.POST.getlist("events")
        languages = self.request.POST.getlist("languages")
        ref_pattern = self.request.POST.get("ref_pattern", "").strip()
        form.instance.criteria = {
            "events": events,
            "ref": ref_pattern,
            "languages": languages,
        }
        test_cases_raw = self.request.POST.get("test_cases", "[]")
        try:
            form.instance.test_cases = json.loads(test_cases_raw)
        except json.JSONDecodeError:
            form.instance.test_cases = []
        self.object = form.save()
        self._save_labels()
        create_policy_version(self.object, self.request.user, "Created")
        messages.success(self.request, f'Policy "{self.object.name}" created.')
        return redirect("policy_detail", pk=self.object.pk)

    def _save_labels(self):
        label_ids = self.request.POST.getlist("labels")
        new_label = self.request.POST.get("new_label", "").strip()
        labels = list(PolicyLabel.objects.filter(pk__in=label_ids, tenant=self.request.tenant))
        if new_label:
            for name in [n.strip() for n in new_label.split(",") if n.strip()]:
                label, _ = PolicyLabel.objects.get_or_create(
                    tenant=self.request.tenant, name=name,
                )
                labels.append(label)
        self.object.labels.set(labels)


class PolicyDetailView(LoginRequiredMixin, DetailView):
    template_name = "pages/policy_detail.html"
    context_object_name = "policy"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return Policy.objects.none()
        return Policy.objects.filter(tenant=tenant).select_related(
            "source_marketplace_policy"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["versions"] = (
            self.object.versions.select_related("changed_by")
            .order_by("-version")[:20]
        )
        return ctx


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
        context["language_choices"] = LANGUAGE_CHOICES
        context["tenant_labels"] = PolicyLabel.objects.filter(tenant=self.request.tenant)
        criteria = self.object.criteria or {}
        context["selected_events"] = criteria.get("events", [])
        context["selected_languages"] = criteria.get("languages", [])
        context["selected_label_ids"] = list(
            self.object.labels.values_list("pk", flat=True)
        )
        context["ref_pattern"] = criteria.get("ref", "")
        context["is_edit"] = True
        return context

    def form_valid(self, form):
        try:
            validate_policy_code(form.cleaned_data.get("code", ""))
        except ValueError as e:
            form.add_error("code", str(e))
            return self.form_invalid(form)
        events = self.request.POST.getlist("events")
        languages = self.request.POST.getlist("languages")
        ref_pattern = self.request.POST.get("ref_pattern", "").strip()
        form.instance.criteria = {
            "events": events,
            "ref": ref_pattern,
            "languages": languages,
        }
        test_cases_raw = self.request.POST.get("test_cases", "[]")
        try:
            form.instance.test_cases = json.loads(test_cases_raw)
        except json.JSONDecodeError:
            form.instance.test_cases = []
        self.object = form.save()
        self._save_labels()
        create_policy_version(self.object, self.request.user, "Updated")
        messages.success(self.request, f'Policy "{self.object.name}" updated.')
        return redirect("policy_detail", pk=self.object.pk)

    def _save_labels(self):
        label_ids = self.request.POST.getlist("labels")
        new_label = self.request.POST.get("new_label", "").strip()
        labels = list(PolicyLabel.objects.filter(pk__in=label_ids, tenant=self.request.tenant))
        if new_label:
            for name in [n.strip() for n in new_label.split(",") if n.strip()]:
                label, _ = PolicyLabel.objects.get_or_create(
                    tenant=self.request.tenant, name=name,
                )
                labels.append(label)
        self.object.labels.set(labels)


class PolicyVersionDetailView(LoginRequiredMixin, DetailView):
    template_name = "pages/policy_version_detail.html"
    context_object_name = "version"

    def get_queryset(self):
        tenant = self.request.tenant
        if not tenant:
            return PolicyVersion.objects.none()
        return PolicyVersion.objects.filter(
            policy__tenant=tenant
        ).select_related("policy", "changed_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["policy"] = self.object.policy
        ctx["is_current"] = not PolicyVersion.objects.filter(
            policy=self.object.policy, version__gt=self.object.version
        ).exists()
        return ctx


@login_required
@require_POST
def revert_policy_version(request, pk):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("policy_list")

    version = get_object_or_404(
        PolicyVersion, pk=pk, policy__tenant=tenant
    )
    policy = version.policy
    policy.code = version.code
    policy.description = version.description
    policy.criteria = version.criteria
    policy.test_cases = version.test_cases
    policy.save()

    # Restore labels
    label_objs = []
    for name in version.labels_snapshot:
        label, _ = PolicyLabel.objects.get_or_create(
            tenant=tenant, name=name
        )
        label_objs.append(label)
    policy.labels.set(label_objs)

    create_policy_version(policy, request.user, f"Reverted to v{version.version}")

    messages.success(request, f'Reverted "{policy.name}" to v{version.version}.')
    return redirect("policy_detail", pk=policy.pk)


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

    # Make LLM policies testable in the editor: attach the workspace's roles so
    # evaluate(project, llm) runs against the mock repo just like a real run.
    if request.tenant:
        from app.application.policy_engine import resolve_llm_roles

        llm_roles = resolve_llm_roles(request.tenant)
        if llm_roles:
            input_config["llm_roles"] = llm_roles

    runner = SandboxRunner()
    result = runner.run(code, input_config)
    return JsonResponse(result)
