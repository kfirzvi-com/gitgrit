from __future__ import annotations

import logging
import re

from django.db.models import QuerySet

from app.domain.events import DomainEvent
from app.domain.identity import resolve_user
from app.domain.models import Policy, PolicyExecution, Project
from app.infrastructure.sandbox.runner import SandboxRunner

logger = logging.getLogger(__name__)



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

        # Language filter (if set, project must have at least one matching language)
        policy_languages = criteria.get("languages", [])
        if policy_languages:
            project_languages = [lang.lower() for lang in (project.languages or [])]
            if not any(lang.lower() in project_languages for lang in policy_languages):
                return False

        return True

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

            access_token = project.platform_connection.access_token
            input_config = {
                "platform": event.platform,
                "project_id": event.external_project_id,
                "access_token": access_token,
                "base_url": project.platform_connection.base_url,
                "full_path": project.full_path,
            }

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

        access_token = project.platform_connection.access_token
        input_config = {
            "platform": project.platform,
            "project_id": project.external_id,
            "access_token": access_token,
            "base_url": project.platform_connection.base_url,
            "full_path": project.full_path,
        }

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
