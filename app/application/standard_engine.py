from __future__ import annotations

import logging
import re

from django.db.models import QuerySet

from app.application.event_bus import publish
from app.domain.events import DomainEvent, RepositoryPushed
from app.domain.identity import resolve_user
from app.domain.models import (
    AuthMethod,
    LLMRole,
    Project,
    Standard,
    StandardExecution,
)
from app.domain.standard_criteria import language_matches
from app.infrastructure.sandbox.runner import SandboxRunner

logger = logging.getLogger(__name__)


def resolve_llm_roles(tenant) -> dict:
    """Resolve a tenant's configured LLM roles into a flat map the sandbox can
    consume: role name -> {model, base_url, api_key}. The model string is
    LiteLLM-formatted (``provider_type/model``). Empty when nothing is set.

    Shared by the StandardEngine (real runs) and the standard editor's test run.
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


class StandardEngine:
    def __init__(self) -> None:
        self._runner = None

    @property
    def runner(self) -> SandboxRunner:
        if self._runner is None:
            self._runner = SandboxRunner()
        return self._runner

    def resolve_projects(
        self, event: DomainEvent, installation_id: int | None = None
    ) -> QuerySet[Project]:
        """Find all projects matching the webhook's platform + external ID.

        ``installation_id`` narrows the match to the GitHub App connections
        holding that installation. An App delivery is authenticated with one
        secret shared by every installation of the App, so without this narrowing
        a delivery would also fire policies in an unrelated workspace that
        happens to connect the same repository by token — a workspace that
        installation was never granted anything by.
        """
        projects = Project.objects.filter(
            platform=event.platform,
            external_id=event.external_project_id,
        ).select_related("platform_connection", "tenant")
        if installation_id is not None:
            projects = projects.filter(
                platform_connection__auth_method=AuthMethod.GITHUB_APP,
                platform_connection__installation_id=installation_id,
            )
        return projects

    def get_standards_for_project(
        self, project: Project, event_type: str, ref: str | None = None
    ) -> list[Standard]:
        """Return the project's attached, enabled, non-draft standards whose
        criteria match the event."""
        standards = project.standards.filter(
            enabled=True,
            draft=False,
        )
        return [
            p
            for p in standards
            if self._matches_criteria(p, event_type, ref, project)
        ]

    def _matches_criteria(
        self,
        standard: Standard,
        event_type: str,
        ref: str | None,
        project: Project,
        skip_event_check: bool = False,
    ) -> bool:
        criteria = standard.criteria or {}

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
                    "Invalid ref regex '%s' in standard '%s'",
                    ref_pattern,
                    standard.name,
                )
                return False

        if not language_matches(criteria.get("languages", []), project.languages or []):
            return False

        return True

    def _build_input_config(self, project: Project) -> dict:
        """Build the /input.json payload for a project run. Attaches llm_roles
        only when the workspace has configured them, so deterministic standards
        are unaffected."""
        input_config = {
            "platform": project.platform,
            "project_id": project.external_id,
            # Route through the auth-method seam. For GitHub App connections the
            # installation token is scoped to this project's repository; PAT
            # connections return their stored token unchanged.
            "access_token": project.platform_connection.get_access_token(
                repositories=[project.full_path]
            ),
            "base_url": project.platform_connection.base_url,
            "full_path": project.full_path,
        }
        llm_roles = resolve_llm_roles(project.tenant)
        if llm_roles:
            input_config["llm_roles"] = llm_roles
        return input_config

    def run_for_event(
        self, event: DomainEvent, installation_id: int | None = None
    ) -> list[dict]:
        projects = self.resolve_projects(event, installation_id=installation_id)

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
            # A code push may change dependencies — trigger a graph refresh
            # (async, additive; does not affect the synchronous standard run below).
            if event.event_type == "push":
                publish(
                    RepositoryPushed(
                        project_id=str(project.id),
                        tenant_id=str(project.tenant_id),
                        ref=event.ref,
                    )
                )

            standards = self.get_standards_for_project(
                project, event.event_type, ref=event.ref
            )

            if not standards:
                logger.info(
                    "No standards matched event_type=%s for project=%s (tenant=%s)",
                    event.event_type,
                    project.name,
                    project.tenant.name,
                )
                continue

            input_config = self._build_input_config(project)

            for standard in standards:
                logger.info(
                    "Running standard '%s' for project '%s' (event=%s)",
                    standard.name,
                    project.name,
                    event.event_type,
                )

                execution = StandardExecution.objects.create(
                    project=project,
                    standard=standard,
                    standard_name=standard.name,
                    event_type=event.event_type,
                    status=StandardExecution.Status.RUNNING,
                    triggered_by=event.actor or "",
                    triggered_by_user=actor_user,
                    ref=event.ref or "",
                )

                result = self.runner.run(standard.code, input_config)

                if result.get("details", {}).get("error"):
                    execution.status = StandardExecution.Status.ERROR
                elif result.get("passed"):
                    execution.status = StandardExecution.Status.PASSED
                else:
                    execution.status = StandardExecution.Status.FAILED

                execution.score = result.get("score", 0)
                execution.message = result.get("message", "")
                execution.details = result.get("details", {})
                execution.logs = result.get("logs", [])
                execution.save()

                result["standard_id"] = str(standard.id)
                result["standard_name"] = standard.name
                result["execution_id"] = str(execution.id)
                result["project_id"] = str(project.id)
                result["project_name"] = project.name
                results.append(result)

        return results

    def run_for_project(
        self, project: Project, standards: list[Standard] | None = None
    ) -> list[dict]:
        """Run standards manually for a project (no webhook event needed).

        With no explicit list, runs all of the project's attached standards.
        """
        if standards is None:
            standards = list(
                project.standards.filter(enabled=True, draft=False)
            )
            # Apply language/ref criteria filtering (skip event check for manual runs)
            standards = [
                p for p in standards
                if self._matches_criteria(
                    p, "manual", ref=None, project=project, skip_event_check=True
                )
            ]

        if not standards:
            return []

        input_config = self._build_input_config(project)

        results = []
        for standard in standards:
            logger.info(
                "Running standard '%s' for project '%s' (manual)",
                standard.name,
                project.name,
            )

            execution = StandardExecution.objects.create(
                project=project,
                standard=standard,
                standard_name=standard.name,
                event_type="manual",
                status=StandardExecution.Status.RUNNING,
                triggered_by="manual",
            )

            result = self.runner.run(standard.code, input_config)

            if result.get("details", {}).get("error"):
                execution.status = StandardExecution.Status.ERROR
            elif result.get("passed"):
                execution.status = StandardExecution.Status.PASSED
            else:
                execution.status = StandardExecution.Status.FAILED

            execution.score = result.get("score", 0)
            execution.message = result.get("message", "")
            execution.details = result.get("details", {})
            execution.logs = result.get("logs", [])
            execution.save()

            result["standard_id"] = str(standard.id)
            result["standard_name"] = standard.name
            result["execution_id"] = str(execution.id)
            result["project_id"] = str(project.id)
            result["project_name"] = project.name
            results.append(result)

        return results
