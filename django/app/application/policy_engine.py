from __future__ import annotations

import logging

from django.db.models import QuerySet

from app.domain.events import DomainEvent
from app.domain.models import Policy, PolicyExecution, Project
from app.infrastructure.sandbox.runner import SandboxRunner

logger = logging.getLogger(__name__)


class PolicyEngine:
    def __init__(self) -> None:
        self.runner = SandboxRunner()

    def resolve_projects(self, event: DomainEvent) -> QuerySet[Project]:
        """Find all projects matching the webhook's platform + external ID."""
        return Project.objects.filter(
            platform=event.platform,
            external_id=event.external_project_id,
        ).select_related("platform_connection", "tenant")

    def get_policies_for_project(
        self, project: Project, event_type: str
    ) -> list[Policy]:
        """Return enabled, non-draft policies whose criteria include the event type."""
        policies = Policy.objects.filter(
            tenant=project.tenant,
            enabled=True,
            draft=False,
        )
        return [
            p
            for p in policies
            if event_type in p.criteria.get("events", [])
        ]

    def run_for_event(self, event: DomainEvent) -> list[dict]:
        projects = self.resolve_projects(event)

        if not projects.exists():
            logger.info(
                "No projects matched platform=%s external_id=%s",
                event.platform,
                event.external_project_id,
            )
            return []

        results = []
        for project in projects:
            policies = self.get_policies_for_project(project, event.event_type)

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
