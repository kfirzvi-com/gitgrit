"""A project's health and commit checks as plain data, scoped to a workspace.

The same reads the project page's Health card makes (``commit_checks`` and
``standard_results``), shaped for the public API.
"""
from django.core.exceptions import ValidationError

from app.application import commit_checks
from app.application.errors import NotFoundError
from app.application.standard_results import breakdown, current_results, project_score
from app.application.standard_runs import in_flight
from app.domain.health import level_from_score
from app.domain.models import Project, StandardExecution, Tenant

Status = StandardExecution.Status


def _result(ex: StandardExecution) -> dict:
    check = ex.commit_check
    data = {
        "execution_id": str(ex.id),
        "standard_id": str(ex.standard_id) if ex.standard_id else None,
        "standard_name": ex.standard_name,
        "status": ex.status,
        "score": ex.score if ex.status != Status.RUNNING else None,
        "message": ex.message,
        "branch": check.branch if check else ex.ref,
        "commit_sha": check.commit_sha if check else "",
        "ran_at": ex.created_at.isoformat(),
    }
    if hasattr(ex, "still_attached"):
        data["still_attached"] = ex.still_attached
    return data


def _summary(results) -> dict:
    score = project_score(results)
    return {"score": score, "level": level_from_score(score), **breakdown(results)}


def _commit(row: commit_checks.CommitRow) -> dict:
    finished = [r for r in row.results if r.status != Status.RUNNING]
    return {
        "sha": row.sha,
        "title": row.title,
        "author": row.author,
        "date": row.date.isoformat() if row.date else None,
        "url": row.url,
        "checked": row.checked,
        "running": row.running,
        **_summary(finished),
        "results": [_result(r) for r in row.results],
        "not_run": [{"id": str(s.id), "name": s.name} for s in row.not_run],
    }


class ProjectHealthService:
    def _project(self, tenant: Tenant, project_id: str) -> Project:
        try:
            return Project.objects.select_related("platform_connection").get(
                tenant=tenant, id=project_id
            )
        except (Project.DoesNotExist, ValidationError):
            raise NotFoundError(f"Project {project_id} not found")

    @staticmethod
    def _running(project: Project, branch: str | None) -> bool:
        runs = StandardExecution.objects.filter(project=project)
        if branch:
            runs = runs.filter(commit_check__branch=branch)
        return in_flight(runs).exists()

    def branches(self, tenant: Tenant, project_id: str) -> list[dict]:
        """Every branch, the default first (from the platform; falls back to
        the branches GitGrit has checked)."""
        project = self._project(tenant, project_id)
        return [
            {"name": name, "is_default": name == project.default_branch}
            for name in commit_checks.branches(project)
        ]

    def health(self, tenant: Tenant, project_id: str, branch: str | None = None) -> dict:
        """The project's health — each attached standard's latest result on
        its home branch — or, with ``branch``, that branch's own health."""
        project = self._project(tenant, project_id)
        if branch:
            results = commit_checks.branch_status(project, branch)
        else:
            results = current_results([project])
        results = sorted(results, key=lambda ex: ex.created_at, reverse=True)
        return {
            "project": {"id": str(project.id), "name": project.name},
            "branch": branch or None,
            "default_branch": project.default_branch,
            **_summary(results),
            "running": self._running(project, branch),
            "results": [_result(ex) for ex in results],
        }

    def commits(self, tenant: Tenant, project_id: str, branch: str | None, page: int = 1) -> dict:
        """One page of a branch's commits, newest first, each with its checks."""
        project = self._project(tenant, project_id)
        branch = branch or project.default_branch
        rows, has_more = commit_checks.branch_commits(project, branch, page)
        return {
            "branch": branch,
            "page": page,
            "has_more": has_more,
            "commits": [_commit(row) for row in rows],
        }

    def commit(self, tenant: Tenant, project_id: str, sha: str) -> dict:
        """One commit's checks, from what GitGrit recorded."""
        project = self._project(tenant, project_id)
        row = commit_checks.commit_results(project, sha)
        if not row.checked:
            raise NotFoundError(f"No checks recorded for commit {sha}")
        return _commit(row)

    def run(self, tenant: Tenant, user, project_id: str, branch: str | None, sha: str = "") -> dict:
        """Check a branch's latest commit, or one commit, now."""
        project = self._project(tenant, project_id)
        run = commit_checks.run_on_branch(
            project, branch or project.default_branch, sha=sha, user=user
        )
        return {
            "branch": run.branch,
            "commit_sha": run.commit_sha or None,
            "queued": run.summary["queued"] if run.summary else 0,
            "already_running": run.summary["already_running"] if run.summary else 0,
            "message": run.notice,
        }
