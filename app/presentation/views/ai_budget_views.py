"""AI budgets in workspace settings: owners and admins set a cap per
provider, model and period; everyone else sees them. Every action answers
with the panel so it updates in place."""
from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from app.application.ai_usage import BudgetableModels, BudgetError, BudgetService, BudgetWatch
from app.domain.ai_usage import BudgetPeriod
from app.domain.models import LLMBudget
from app.presentation.budget_row import BudgetRow
from app.presentation.htmx import toast
from app.workspace_access import is_workspace_admin


def ai_budgets_context(tenant, is_admin: bool) -> dict:
    budgets = LLMBudget.objects.filter(tenant=tenant).select_related("provider").order_by(
        "provider__display_name", "model", "period"
    )
    options = [
        (m.provider_id, m.provider_name, m.model, ", ".join(m.roles))
        for m in BudgetableModels.for_workspace(tenant)
    ]
    return {
        "budget_rows": [BudgetRow(b, BudgetWatch.used(b)) for b in budgets],
        "budget_model_options": options,
        "budget_periods": list(BudgetPeriod),
        "is_admin": is_admin,
    }


def _panel(request):
    return render(
        request,
        "partials/ai_budgets_panel.html",
        ai_budgets_context(request.tenant, is_workspace_admin(request)),
    )


def _answer(request, error=None, success=None, event=None):
    """In place (the panel, with a toast) for HTMX; a redirect otherwise.
    ``event`` is also triggered on success (the dialog closes on it); an
    error leaves the dialog open to fix."""
    if request.htmx:
        response = toast(_panel(request), error or success, "error" if error else "success")
        if event and not error:
            triggers = json.loads(response["HX-Trigger"])
            triggers[event] = None
            response["HX-Trigger"] = json.dumps(triggers)
        return response
    if error:
        messages.error(request, error)
    else:
        messages.success(request, success)
    return redirect(reverse("tenant_settings") + "#section-llm")


@login_required
@require_POST
def save_ai_budget(request):
    if not request.tenant or not is_workspace_admin(request):
        return _answer(request, error="Only workspace owners and admins can set AI budgets.")
    provider_id, _, model = request.POST.get("model_key", "").partition("|")
    try:
        budget = BudgetService.save(
            request.tenant,
            provider_id=provider_id,
            model=model,
            period=request.POST.get("period", ""),
            input_limit=request.POST.get("input_limit"),
            output_limit=request.POST.get("output_limit"),
            stop_at_limit=request.POST.get("stop_at_limit") == "on",
            low_at_percent=request.POST.get("low_at_percent"),
            budget_id=request.POST.get("budget_id") or None,
        )
    except BudgetError as exc:
        return _answer(request, error=str(exc))
    return _answer(request, success=f"{BudgetPeriod(budget.period).label} budget saved for {budget.provider.display_name} {budget.model}.",
                   event="aiBudgetSaved")


@login_required
@require_POST
def delete_ai_budget(request, budget_id):
    if not request.tenant or not is_workspace_admin(request):
        return _answer(request, error="Only workspace owners and admins can remove AI budgets.")
    BudgetService.delete(request.tenant, budget_id)
    return _answer(request, success="Budget removed.")
