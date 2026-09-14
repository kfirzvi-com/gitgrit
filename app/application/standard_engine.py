from __future__ import annotations

import logging
import re

from django.db.models import QuerySet

from app.domain.events import DomainEvent
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

_REF_PREFIX = re.compile(r"^refs/(heads|tags)/")
_REGEX_CHARS = re.compile(r"[*+?()\[\]{}|\\]")


def bare_ref(ref: str | None) -> str:
    """Strip the refs/heads/ or refs/tags/ prefix a webhook ref carries."""
    return _REF_PREFIX.sub("", ref or "")


def literal_ref(pattern: str | None) -> str:
    """Return the branch or tag a Branch/Tag Filter names literally, or ""
    when the filter is empty or a regex. ``main`` and ``^main$`` both name
    ``main``; ``^release/.*`` names nothing, so runs fall back to the default
    branch."""
    name = (pattern or "").strip().removeprefix("^").removesuffix("$")
    if not name or _REGEX_CHARS.search(name):
        return ""
    return name


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
        a delivery would also fire standards in an unrelated workspace that
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
        self,
        project: Project,
        event_type: str,
        ref: str | None = None,
        target_ref: str | None = None,
    ) -> list[Standard]:
        """Return the project's attached, enabled, non-draft standards whose
        criteria match the event. ``target_ref`` is a pull request's target
        branch; when given, the Branch/Tag Filter matches it instead of ``ref``."""
        standards = project.standards.filter(
            enabled=True,
            draft=False,
        )
        return [
            p
            for p in standards
            if self._matches_criteria(
                p, event_type, ref, project, target_ref=target_ref
            )
        ]

    def runnable_standards(
        self, project: Project, standards: list[Standard]
    ) -> list[Standard]:
        """Filter to the standards that would run on a manual check of this
        project: enabled, non-draft, and criteria-matching (event check
        skipped, like manual runs)."""
        return [
            s
            for s in standards
            if s.enabled
            and not s.draft
            and self._matches_criteria(
                s, "manual", ref=None, project=project, skip_event_check=True
            )
        ]

    def _matches_criteria(
        self,
        standard: Standard,
        event_type: str,
        ref: str | None,
        project: Project,
        skip_event_check: bool = False,
        target_ref: str | None = None,
    ) -> bool:
        criteria = standard.criteria or {}

        # Event type must match (unless skipped for manual runs)
        if not skip_event_check and event_type not in criteria.get("events", []):
            return False

        # Branch/Tag Filter. Matched against the branch the event is *for*: a
        # pull request's target branch, else the pushed branch or tag. Empty
        # matches all branches and tags. Events that carry no ref (and manual
        # runs) skip the check.
        ref_pattern = criteria.get("ref", "").strip()
        filter_ref = bare_ref(target_ref or ref)
        if ref_pattern and filter_ref:
            try:
                if not re.search(ref_pattern, filter_ref):
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

    def build_input_config(self, project: Project, ref: str | None = None) -> dict:
        """Build the /input.json payload for a project run. Attaches llm_roles
        only when the workspace has configured them, so deterministic standards
        are unaffected. ``ref`` is the branch or tag the sandbox reads the
        repository at; empty means the default branch. The background job
        builds this once per project (it fetches the access token) and
        ``run_execution`` overlays each execution's own ref."""
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
            "ref": bare_ref(ref),
        }
        llm_roles = resolve_llm_roles(project.tenant)
        if llm_roles:
            input_config["llm_roles"] = llm_roles
        return input_config

    def run_execution(self, execution: StandardExecution, input_config: dict) -> dict:
        """Run one already-created ``StandardExecution`` and record its result.

        The single place a standard's code meets the sandbox. The repository
        is read at ``execution.ref``, fixed when the row was created: the
        event's branch for webhook runs, the branch the Branch/Tag Filter
        names for manual runs, or "" for the default branch. Fills in status
        (error beats passed, so each result lands in exactly one bucket),
        score, message, details and logs, then returns the runner's result
        enriched with the standard/execution/project identity.
        """
        standard = execution.standard
        project = execution.project

        logger.info(
            "Running standard '%s' for project '%s' (event=%s)",
            standard.name,
            project.name,
            execution.event_type,
        )
        result = self.runner.run(
            standard.code, {**input_config, "ref": bare_ref(execution.ref)}
        )

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
        return result
