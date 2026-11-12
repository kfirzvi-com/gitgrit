from __future__ import annotations

import logging

from app.application.ai_usage.budget_watch import BudgetWatch
from app.domain.ai_usage import TokenCount, UsageCategory
from app.domain.models import LLMProvider, LLMUsage

logger = logging.getLogger(__name__)


class UsageRecorder:
    """Stores the tokens one model spent on one piece of work, then lets the
    model's budgets react. Recording never fails the work it records."""

    @staticmethod
    def record(*, tenant, provider_id, model: str, category: UsageCategory, tokens: TokenCount,
               project=None, standard=None, execution=None) -> LLMUsage | None:
        if not tokens.total and not tokens.calls:
            return None
        try:
            provider = LLMProvider.objects.filter(tenant=tenant, pk=provider_id).first() if provider_id else None
            usage = LLMUsage.objects.create(
                tenant=tenant,
                provider=provider,
                provider_name=provider.display_name if provider else "Unknown provider",
                model=model or "unknown",
                category=str(category),
                input_tokens=tokens.input,
                output_tokens=tokens.output,
                calls=tokens.calls,
                project=project,
                standard=standard,
                standard_name=standard.name if standard else "",
                execution=execution,
            )
            if provider:
                BudgetWatch.check(tenant, provider.pk, usage.model)
            return usage
        except Exception:  # noqa: BLE001 — never lose the run over bookkeeping
            logger.exception("Could not record AI usage for %s/%s", provider_id, model)
            return None


    @classmethod
    def record_standard_run(cls, execution, llm_usage: dict, llm_roles: dict) -> None:
        """Bill one LLM-standard run's tokens to each model it used. A run from
        an older sandbox reports only totals; those go to the reasoning role's
        model (the role standards use by default)."""
        if not llm_usage:
            return
        project = execution.project
        per_model = list((llm_usage.get("by_model") or {}).values())
        if not per_model:
            role = llm_roles.get("reasoning") or next(iter(llm_roles.values()), {})
            per_model = [{
                "provider_id": role.get("provider_id"),
                "model": role.get("model_name") or role.get("model", ""),
                "prompt_tokens": llm_usage.get("prompt_tokens", 0),
                "completion_tokens": llm_usage.get("completion_tokens", 0),
                "calls": llm_usage.get("calls", 0),
            }]
        for row in per_model:
            cls.record(
                tenant=project.tenant,
                provider_id=row.get("provider_id"),
                model=row.get("model", ""),
                category=UsageCategory.STANDARD,
                tokens=TokenCount(int(row.get("prompt_tokens") or 0), int(row.get("completion_tokens") or 0),
                                  int(row.get("calls") or 0)),
                project=project,
                standard=execution.standard,
                execution=execution,
            )
