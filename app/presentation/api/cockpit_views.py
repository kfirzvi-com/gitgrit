"""Public API for what the dashboard shows: the overview (the cockpit), AI
usage, the models a budget can cover, AI budgets, and stacks' health. Thin
wrappers over the same application reads the pages use."""
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, status
from rest_framework.response import Response

from app.application.ai_usage import AIUsageReport, BudgetableModelsQuery, BudgetError, BudgetService, BudgetWatch
from app.application.cockpit import Cockpit, HealthTrend
from app.application.dependency_agent import refresh_stack_map
from app.application.project_health_counts import ProjectHealthCounts
from app.application.stack_health import StackHealth
from app.domain.ai_usage import BudgetPeriod, BudgetSummary
from app.domain.models import LLMBudget, Stack
from app.domain.score_representation import ScoreTone
from app.presentation.api import cockpit_serializers as cs
from app.presentation.api.views import WorkspaceAPIView
from app.presentation.health_note import HealthNote

_PERIOD = OpenApiParameter(
    "period", str, required=False, enum=cs.PERIOD_CHOICES, description="The current day, week or month (default)."
)


def _project(project) -> dict:
    return {"id": str(project.pk), "name": project.name}


def _grade(project, score):
    """How the app shows the project's score; None when it has none."""
    if score is None:
        return None
    return project.tenant.score_representation.represent(score.value, failed=score.failed).as_dict()


def _budget(budget: LLMBudget, used, now) -> dict:
    period = BudgetPeriod(budget.period)
    rules = budget.rules
    return {
        "id": str(budget.pk),
        "provider": {"id": str(budget.provider_id), "name": budget.provider.display_name},
        "model": budget.model,
        "period": str(period),
        "input_limit": budget.input_limit,
        "output_limit": budget.output_limit,
        "low_at_percent": budget.low_at_percent,
        "stop_at_limit": budget.stop_at_limit,
        "used": {"input_tokens": used.input, "output_tokens": used.output},
        "level": str(rules.level(used)),
        "stops_runs": rules.stops_runs(used),
        "window": {
            "starts": period.starts(now).isoformat(),
            "last_day": period.last_day(now).isoformat(),
            "resets": period.ends(now).isoformat(),
        },
    }


def _ai_budget_light(summary: BudgetSummary) -> dict:
    """The low-fuel lamp: lit when a budget is low or used up."""
    lit = bool(summary.near or summary.used_up)
    return {
        "key": "ai_budget",
        "title": "AI budget low",
        "count": summary.near + summary.used_up,
        "lit": lit,
        "tone": str(ScoreTone.FAILED if summary.used_up else ScoreTone.NEEDS_ATTENTION),
    }


def _workspace_budgets(tenant, now) -> list:
    budgets = LLMBudget.objects.filter(tenant=tenant).select_related("provider").order_by("model", "period")
    return [(b, BudgetWatch.used(b, now)) for b in budgets]


def _stack_counts(stack, health: ProjectHealthCounts) -> dict:
    return {
        "id": str(stack.pk),
        "name": stack.name,
        "description": stack.description,
        "project_count": health.total,
        "failed": health.failed,
        "needs_attention": health.needs_attention,
        "healthy": health.healthy,
    }


class OverviewView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_overview",
        tags=["overview"],
        summary="The workspace at a glance: health, warning lights, what needs you",
        description=(
            "What the dashboard's cockpit shows: projects counted by health (never one grade for many), "
            "the warning lights (each lit only when something needs action), the projects that need you, "
            "commits checked per week and healthy projects week by week."
        ),
        responses={200: cs.OverviewSerializer},
    )
    def get(self, request, workspace_id):
        cockpit = Cockpit.for_workspace(self.tenant)
        health = cockpit.health
        budgets = BudgetSummary.of((b.rules, used) for b, used in _workspace_budgets(self.tenant, timezone.localtime()))
        last = cockpit.last_check
        return Response({
            "health": {
                "total": health.total,
                "failed": health.failed,
                "needs_attention": health.needs_attention,
                "healthy": health.healthy,
                "checked": health.checked,
                "unchecked": health.unchecked,
            },
            "lights": [
                {"key": light.key, "title": light.title, "count": light.count, "lit": light.lit, "tone": str(light.tone)}
                for light in cockpit.lights
            ] + [_ai_budget_light(budgets)],
            "needs_you": [
                {
                    "project": _project(row.project),
                    "tone": str(row.tone),
                    "grade": _grade(row.project, row.score),
                    "why": HealthNote.text(row.score, row.below_par),
                    "owner": row.owner or "",
                    "stacks": list(row.stacks),
                }
                for row in cockpit.rows
            ],
            "last_check": last and {
                "at": last.created_at.isoformat(),
                "project": _project(last.project),
                "commit_sha": last.commit_sha,
                "branch": last.branch,
            },
            "checks": {
                "this_week": cockpit.checks_this_week,
                "last_week": cockpit.checks_last_week,
                "peak": cockpit.checks_peak,
            },
            "trend": [
                {"day": p.day.isoformat(), "healthy": p.healthy, "total": p.total}
                for p in HealthTrend.weekly(self.tenant)
            ],
        })


class AIUsageView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_ai_usage",
        tags=["ai"],
        summary="AI tokens spent this day, week or month",
        description=(
            "Input and output tokens per provider and model (models are priced apart, so never added up "
            "across models), each model's budgets, tokens per kind of work, and how LLM-standard tokens "
            "split between standards."
        ),
        parameters=[_PERIOD],
        responses={200: cs.AIUsageSerializer},
    )
    def get(self, request, workspace_id):
        try:
            period = BudgetPeriod(request.query_params.get("period", "month"))
        except ValueError:
            raise exceptions.ValidationError({"period": "Pick day, week or month."}) from None
        now = timezone.localtime()
        report = AIUsageReport.for_workspace(self.tenant, period, now)
        dist = report.standards
        summary = BudgetSummary.of(
            (b.rules, used) for p in report.providers for m in p.models for b, used in m.budgets
        )
        return Response({
            "period": str(period),
            "starts": period.starts(now).isoformat(),
            "budgets": {
                "total": summary.total, "ok": summary.ok, "near": summary.near,
                "used_up": summary.used_up, "stopping": summary.stopping,
            },
            "providers": [
                {
                    "id": str(p.provider_id) if p.provider_id else None,
                    "name": p.name,
                    "models": [
                        {
                            "model": m.model,
                            "input_tokens": m.tokens.input,
                            "output_tokens": m.tokens.output,
                            "calls": m.tokens.calls,
                            "blocked": not m.budgets,
                            "budgets": [_budget(b, used, now) for b, used in m.budgets],
                        }
                        for m in p.models
                    ],
                }
                for p in report.providers
            ],
            "categories": [
                {
                    "category": str(c), "label": c.label,
                    "input_tokens": t.input, "output_tokens": t.output, "calls": t.calls,
                }
                for c, t in report.categories
            ],
            "standards": [
                {
                    "standard_id": str(s.standard_id) if s.standard_id else None,
                    "name": s.name,
                    "input_tokens": s.tokens.input,
                    "output_tokens": s.tokens.output,
                    "runs": s.runs,
                    "share": round(dist.share(s), 4),
                    "heavy": dist.is_heavy(s),
                    "times_median": dist.times_median(s),
                }
                for s in dist.standards
            ],
        })


class AIModelsView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_ai_models",
        tags=["ai"],
        summary="Models a budget can cover",
        description="Only models with a budget run: a model without one is blocked.",
        responses={200: cs.BudgetableModelSerializer(many=True)},
    )
    def get(self, request, workspace_id):
        return Response([
            {
                "provider": {"id": m.provider_id, "name": m.provider_name},
                "model": m.model,
                "roles": list(m.roles),
                "has_budget": m.has_budget,
                "blocked": m.blocked,
            }
            for m in BudgetableModelsQuery.for_workspace(self.tenant)
        ])


class AIBudgetsView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_ai_budgets",
        tags=["ai"],
        summary="AI budgets, with what each current period has used",
        responses={200: cs.BudgetSerializer(many=True)},
    )
    def get(self, request, workspace_id):
        now = timezone.localtime()
        return Response([_budget(b, used, now) for b, used in _workspace_budgets(self.tenant, now)])

    @extend_schema(
        operation_id="create_ai_budget",
        tags=["ai"],
        summary="Set a budget on a model (owners and admins)",
        description="One budget per provider, model and period. A model runs only once it has a budget.",
        request=cs.BudgetCreateSerializer,
        responses={201: cs.BudgetSerializer},
    )
    def post(self, request, workspace_id):
        self.require_admin()
        data = cs.BudgetCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        budget = _save(self.tenant, {"input_limit": None, "output_limit": None, **data.validated_data})
        return Response(_budget(budget, BudgetWatch.used(budget), timezone.localtime()), status=status.HTTP_201_CREATED)


class AIBudgetView(WorkspaceAPIView):
    def _get(self, budget_id) -> LLMBudget:
        budget = LLMBudget.objects.filter(tenant=self.tenant, pk=budget_id).select_related("provider").first()
        if budget is None:
            raise exceptions.NotFound("Budget not found.")
        return budget

    @extend_schema(
        operation_id="update_ai_budget",
        tags=["ai"],
        summary="Change a budget (owners and admins)",
        request=cs.BudgetUpdateSerializer,
        responses={200: cs.BudgetSerializer},
    )
    def patch(self, request, workspace_id, budget_id):
        self.require_admin()
        budget = self._get(budget_id)
        data = cs.BudgetUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        fields = {
            "provider_id": budget.provider_id,
            "model": budget.model,
            "period": budget.period,
            "input_limit": budget.input_limit,
            "output_limit": budget.output_limit,
            "low_at_percent": budget.low_at_percent,
            "stop_at_limit": budget.stop_at_limit,
            **data.validated_data,
        }
        budget = _save(self.tenant, fields, budget_id=budget.pk)
        return Response(_budget(budget, BudgetWatch.used(budget), timezone.localtime()))

    @extend_schema(
        operation_id="delete_ai_budget",
        tags=["ai"],
        summary="Remove a budget (owners and admins)",
        description="With no budget left, the model stops running.",
        responses={204: None},
    )
    def delete(self, request, workspace_id, budget_id):
        self.require_admin()
        BudgetService.delete(self.tenant, self._get(budget_id).pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _save(tenant, fields: dict, budget_id=None) -> LLMBudget:
    try:
        return BudgetService.save(tenant, budget_id=budget_id, **fields)
    except BudgetError as exc:
        raise exceptions.ValidationError({"detail": str(exc)}) from None


class StackListView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_stacks",
        tags=["stacks"],
        summary="Stacks, each with its projects counted by health",
        description="Worst first: most failed, then most needing attention, then by name.",
        responses={200: cs.StackSummarySerializer(many=True)},
    )
    def get(self, request, workspace_id):
        stacks = list(Stack.objects.filter(tenant=self.tenant).prefetch_related("components__project"))
        health = ProjectHealthCounts.for_stacks(stacks)
        rows = sorted(
            ((stack, health[stack.pk]) for stack in stacks),
            key=lambda row: (-row[1].failed, -row[1].needs_attention, row[0].name.lower()),
        )
        return Response([_stack_counts(stack, counts) for stack, counts in rows])


class StackDetailView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_stack",
        tags=["stacks"],
        summary="A stack's health and its components, worst first",
        responses={200: cs.StackDetailSerializer},
    )
    def get(self, request, workspace_id, stack_id):
        stack = _stack(self.tenant, stack_id)
        view = StackHealth.of(stack)
        return Response({
            **_stack_counts(stack, view.health),
            "project_count": view.project_count,
            "standard_count": view.standard_count,
            "map_updated_at": view.map_updated_at.isoformat() if view.map_updated_at else None,
            "map_refreshing": view.map_refreshing,
            "components": [
                {
                    "id": str(row.component.pk),
                    "name": row.component.name,
                    "path": row.component.path,
                    "project": _project(row.component.project),
                    "tone": str(row.tone),
                    "grade": _grade(row.component.project, row.score),
                    "why": HealthNote.text(row.score),
                    "last_checked": row.score.created_at.isoformat() if row.score else None,
                }
                for row in view.components
            ],
        })


class StackRefreshView(WorkspaceAPIView):
    @extend_schema(
        operation_id="refresh_stack_map",
        tags=["stacks"],
        summary="Rebuild a stack's map from its projects' main branches (superusers)",
        description="Queued; the worker reads each project. It costs one LLM run per project.",
        request=None,
        responses={202: cs.StackRefreshSerializer},
    )
    def post(self, request, workspace_id, stack_id):
        if self.actor is None or not self.actor.is_superuser:
            raise exceptions.PermissionDenied("Only superusers can refresh a map: it costs one LLM run per project.")
        queued = refresh_stack_map(_stack(self.tenant, stack_id))
        return Response({"queued": queued}, status=status.HTTP_202_ACCEPTED)


def _stack(tenant, stack_id) -> Stack:
    stack = Stack.objects.filter(tenant=tenant, pk=stack_id).first()
    if stack is None:
        raise exceptions.NotFound("Stack not found.")
    return stack
