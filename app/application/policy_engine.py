from __future__ import annotations

import logging
import re

from django.db.models import QuerySet

from app.domain.events import DomainEvent
from app.domain.identity import resolve_user
from app.domain.models import LLMRole, Policy, PolicyExecution, Project
from app.domain.policy_criteria import language_matches
from app.infrastructure.sandbox.runner import SandboxRunner

logger = logging.getLogger(__name__)


def resolve_llm_roles(tenant) -> dict:
    """Resolve a tenant's configured LLM roles into a flat map the sandbox can
    consume: role name -> {model, base_url, api_key}. The model string is
    LiteLLM-formatted (``provider_type/model``). Empty when nothing is set.

    Shared by the PolicyEngine (real runs) and the policy editor's test run.
    """
    roles = LLMRole.objects.filter(
        tenant=tenant, provider__enabled=True
    ).select_related("provider")
    return {
        role.name: {
            "model": f"{role.provider.provider_type}/{role.model}",
            "base_url": role.provider.base_url,
            "api_key": role.provider.api_key,  # decrypted here; plaintext only in /input.json
        }
        for role in roles
    }


class PolicyEngine:
    def __init__(self) -> None:
        self._runner = None

    @property
    def runner(self) -> SandboxRunner:
        if self._runner is None:
            self._runner = SandboxRunner()
        return self._runner

    def resolve_projects(self, event: DomainEvent) -> QuerySet[Project]:
        """Find all projects matching the webhook's platform + external ID."""
        return Project.objects.filter(
            platform=event.platform,
            external_id=event.external_project_id,
        ).select_related("platform_connection", "tenant")

    def get_policies_for_project(
        self, project: Project, event_type: str, ref: str | None = None
    ) -> list[Policy]:
        """Return enabled, non-draft policies whose criteria match the event."""
        policies = Policy.objects.filter(
            tenant=project.tenant,
            enabled=True,
            draft=False,
        )
        return [
            p
            for p in policies
            if self._matches_criteria(p, event_type, ref, project)
        ]

    def _matches_criteria(
        self,
        policy: Policy,
        event_type: str,
        ref: str | None,
        project: Project,
        skip_event_check: bool = False,
    ) -> bool:
        criteria = policy.criteria or {}

        # Event type must match (unless skipped for manual runs)
        if not skip_event_check and event_type not in criteria.get("events", []):
            return False

        # Ref regex filter (if set, ref must match)
        ref_pattern = criteria.get("ref", "").strip()
        if ref_pattern and ref:
            # Strip refs/heads/ prefix for cleaner matching
            bare_ref = re.sub(r"^refs/(heads|tags)/", "", ref)
            try:
                if not re.search(ref_pattern, bare_ref):
                    return False
            except re.error:
                logger.warning(
                    "Invalid ref regex '%s' in policy '%s'",
                    ref_pattern,
                    policy.name,
                )
                return False

        if not language_matches(criteria.get("languages", []), project.languages or []):
            return False

        return True

    def _build_input_config(self, project: Project) -> dict:
        """Build the /input.json payload for a project run. Attaches llm_roles
        only when the workspace has configured them, so deterministic policies
        are unaffected."""
        input_config = {
            "platform": project.platform,
            "project_id": project.external_id,
            "access_token": project.platform_connection.access_token,
            "base_url": project.platform_connection.base_url,
            "full_path": project.full_path,
        }
        llm_roles = resolve_llm_roles(project.tenant)
        if llm_roles:
            input_config["llm_roles"] = llm_roles
        return input_config

    def run_for_event(self, event: DomainEvent) -> list[dict]:
        projects = self.resolve_projects(event)

        if not projects.exists():
            logger.info(
                "No projects matched platform=%s external_id=%s",
                event.platform,
                event.external_project_id,
            )
            return []

        # Resolve the platform actor to a GitGrit user (once per event)
        actor_user = resolve_user(event.platform, event.actor)

        results = []
        for project in projects:
            policies = self.get_policies_for_project(
                project, event.event_type, ref=event.ref
            )

            if not policies:
                logger.info(
                    "No policies matched event_type=%s for project=%s (tenant=%s)",
                    event.event_type,
                    project.name,
                    project.tenant.name,
                )
                continue

            input_config = self._build_input_config(project)

            for policy in policies:
                logger.info(
                    "Running policy '%s' for project '%s' (event=%s)",
                    policy.name,
                    project.name,
                    event.event_type,
                )

                execution = PolicyExecution.objects.create(
                    project=project,
                    policy=policy,
                    policy_name=policy.name,
                    event_type=event.event_type,
                    status=PolicyExecution.Status.RUNNING,
                    triggered_by=event.actor or "",
                    triggered_by_user=actor_user,
                    ref=event.ref or "",
                )

                result = self.runner.run(policy.code, input_config)

                if result.get("details", {}).get("error"):
                    execution.status = PolicyExecution.Status.ERROR
                elif result.get("passed"):
                    execution.status = PolicyExecution.Status.PASSED
                else:
                    execution.status = PolicyExecution.Status.FAILED

                execution.score = result.get("score", 0)
                execution.message = result.get("message", "")
                execution.details = result.get("details", {})
                execution.save()

                result["policy_id"] = str(policy.id)
                result["policy_name"] = policy.name
                result["execution_id"] = str(execution.id)
                result["project_id"] = str(project.id)
                result["project_name"] = project.name
                results.append(result)

        return results

    def run_for_project(
        self, project: Project, policies: list[Policy] | None = None
    ) -> list[dict]:
        """Run policies manually for a project (no webhook event needed)."""
        if policies is None:
            policies = list(
                Policy.objects.filter(
                    tenant=project.tenant, enabled=True, draft=False
                )
            )
            # Apply language/ref criteria filtering (skip event check for manual runs)
            policies = [
                p for p in policies
                if self._matches_criteria(
                    p, "manual", ref=None, project=project, skip_event_check=True
                )
            ]

        if not policies:
            return []

        input_config = self._build_input_config(project)

        results = []
        for policy in policies:
            logger.info(
                "Running policy '%s' for project '%s' (manual)",
                policy.name,
                project.name,
            )

            execution = PolicyExecution.objects.create(
                project=project,
                policy=policy,
                policy_name=policy.name,
                event_type="manual",
                status=PolicyExecution.Status.RUNNING,
                triggered_by="manual",
            )

            result = self.runner.run(policy.code, input_config)

            if result.get("details", {}).get("error"):
                execution.status = PolicyExecution.Status.ERROR
            elif result.get("passed"):
                execution.status = PolicyExecution.Status.PASSED
            else:
                execution.status = PolicyExecution.Status.FAILED

            execution.score = result.get("score", 0)
            execution.message = result.get("message", "")
            execution.details = result.get("details", {})
            execution.save()

            result["policy_id"] = str(policy.id)
            result["policy_name"] = policy.name
            result["execution_id"] = str(execution.id)
            result["project_id"] = str(project.id)
            result["project_name"] = project.name
            results.append(result)

        return results
