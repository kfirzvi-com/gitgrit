from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from django.db.models import QuerySet

from app.domain.events import DomainEvent
from app.domain.models import (
    AuthMethod,
    LLMRole,
    Project,
    Standard,
    StandardExecution,
)
from app.domain.standard_criteria import applies, bare_ref, literal_ref  # noqa: F401 (re-exported)
from app.infrastructure import archives, upload_storage
from app.infrastructure.sandbox.runner import SANDBOX_TMP, SandboxRunner

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
        # Artifact projects: commit SHA -> host directory holding that commit's
        # extracted files, shared by every run of the job (see close()).
        self._commit_dirs: dict[str, str] = {}

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

    def standards_for_branch(self, project: Project, branch: str) -> list[Standard]:
        """The project's current runnable standards that apply to ``branch``:
        attached, enabled, non-draft, matching its languages, and whose
        Branch/Tag Filter (if any) matches the branch. What a manual run on a
        branch or one of its commits runs."""
        return [
            s
            for s in project.standards.filter(enabled=True, draft=False)
            if self._matches_criteria(s, "manual", ref=branch, project=project, skip_event_check=True)
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
        """``app.domain.standard_criteria.applies`` for one standard."""
        return applies(
            standard.criteria,
            project_languages=project.languages,
            event_type=event_type,
            ref=ref,
            target_ref=target_ref,
            skip_event_check=skip_event_check,
        )

    def _commit_dir(self, project: Project, read_at: str) -> str | None:
        """The host directory holding the files of the artifact project's
        commit a run reads: the commit whose SHA ``read_at`` is, else the
        latest one on the branch it names. None when there is none.
        Extracted once per job, under the directory the sandbox can mount."""
        commits = project.artifact_commits.order_by("-created_at")
        commit = commits.filter(sha=read_at).first() if read_at else None
        if commit is None:
            commit = commits.filter(branch=read_at or project.default_branch).first()
        if commit is None:
            return None
        if commit.sha not in self._commit_dirs:
            Path(SANDBOX_TMP).mkdir(parents=True, exist_ok=True)
            target = Path(tempfile.mkdtemp(prefix="commit-", dir=SANDBOX_TMP))
            target.chmod(0o755)  # the sandbox's user must be able to read it
            try:
                archives.extract(upload_storage.read_archive(commit.archive_key), target)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
            self._commit_dirs[commit.sha] = str(target)
        return self._commit_dirs[commit.sha]

    def close(self) -> None:
        """Remove the commit files extracted for this job's runs."""
        for path in self._commit_dirs.values():
            shutil.rmtree(path, ignore_errors=True)
        self._commit_dirs.clear()

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
            "full_path": project.full_path,
            "ref": bare_ref(ref),
        }
        # An artifact project's files are mounted into the sandbox (see
        # run_execution): no platform to call, no token to call it with.
        if not project.is_artifact:
            # Route through the auth-method seam. For GitHub App connections the
            # installation token is scoped to this project's repository; PAT
            # connections return their stored token unchanged.
            input_config["access_token"] = project.platform_connection.get_access_token(
                repositories=[project.full_path]
            )
            input_config["base_url"] = project.platform_connection.base_url
        llm_roles = resolve_llm_roles(project.tenant)
        if llm_roles:
            input_config["llm_roles"] = llm_roles
        return input_config

    def run_execution(self, execution: StandardExecution, input_config: dict) -> dict:
        """Run one already-created ``StandardExecution`` and record its result.

        The single place a standard's code meets the sandbox. The repository
        is read at the commit its ``CommitCheck`` is pinned to, so every
        standard of a check reads the same code; a run with no pinned commit
        reads ``execution.ref``: the event's branch for webhook runs, the
        branch the Branch/Tag Filter names for manual runs, or "" for the
        default branch. Fills in status
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
        check = execution.commit_check
        read_at = (check.commit_sha if check else "") or bare_ref(execution.ref)
        # The snapshot recorded when the run was queued, so a standard edited
        # in between does not run code other than the one on record.
        version = execution.standard_version
        code = version.code if version else standard.code
        config = {**input_config, "ref": read_at}
        if not project.is_artifact:
            result = self.runner.run(code, config)
        elif project_dir := self._commit_dir(project, read_at):
            result = self.runner.run(code, config, project_dir=project_dir)
        else:
            branch = bare_ref(execution.ref) or project.default_branch
            message = f"No commit of {project.name} has been uploaded to {branch} yet."
            result = {"passed": False, "score": 0, "message": message, "details": {"error": True}}

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
