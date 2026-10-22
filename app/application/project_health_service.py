"""A project's health and commit checks as plain data, scoped to a workspace.

The same reads the project page makes (``commit_checks`` and ``scoring``),
shaped for the public API. Every score comes with a ``commit_score`` object
(``_commit_score``): the commit's one outcome (checking, no_score, failed or
scored), its value (only when scored), and why it failed or has no score.
"""
from django.core.exceptions import ValidationError

from app.application import commit_checks, scoring
from app.application.errors import NotFoundError
from app.application.standard_results import breakdown
from app.application.standard_runs import in_flight
from app.domain.scoring import CommitScoreOutcome, CommitStanding
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


def _summary(project, score, results) -> dict:
    value = score.value if score else None
    return {
        "score": value,
        "score_display": _display(project, score),
        **breakdown(results),
    }


def _display(project, score) -> dict:
    """How the app shows ``score`` (a CommitScore or None): as the project's
    workspace reads scores, letters or numbers."""
    return project.tenant.score_representation.represent(
        score.value if score else None, failed=bool(score and score.failed)
    ).as_dict()


def _verdict_standing(score) -> CommitStanding:
    """A branch's verdict (a saved failed or scored CommitScore) as a
    standing: every standard it expected has a result."""
    count = score.executions.count()
    return CommitStanding(score.outcome, score.reason, count, count, score.value)


def _commit_score(project, sha: str, branch: str, standing: CommitStanding | None, committed_at=None) -> dict | None:
    """A commit's score as the API shows it: its one ``outcome`` (checking,
    no_score, failed or scored), ``value`` (only when scored), ``reason``
    (why it failed or has no score), how this workspace shows it, and how
    many of the standards its newest check expects have a result."""
    if standing is None:
        return None
    return {
        "outcome": str(standing.outcome),
        "value": standing.value,
        "reason": standing.reason,
        "display": project.tenant.score_representation.represent(
            standing.value, failed=standing.outcome is CommitScoreOutcome.FAILED
        ).as_dict(),
        "standards": {"expected": standing.expected_count, "finished": standing.finished_count},
        "commit": {
            "sha": sha,
            "branch": branch,
            "committed_at": committed_at.isoformat() if committed_at else None,
        },
    }


def _commit(project, row: commit_checks.CommitRow, branch: str) -> dict:
    finished = [r for r in row.results if r.status != Status.RUNNING]
    return {
        "sha": row.sha,
        "title": row.title,
        "author": row.author,
        "date": row.date.isoformat() if row.date else None,
        "url": row.url,
        "checked": row.checked,
        "running": row.running,
        **_summary(project, row.commit_score, finished),
        "commit_score": (
            _commit_score(
                project,
                row.sha,
                branch,
                scoring.commit_standing(project, row.sha, branch),
                row.commit_score.committed_at if row.commit_score else None,
            )
            if row.checked
            else None
        ),
        "results": [_result(r) for r in row.results],
        "expected_but_never_ran": [{"id": str(s.id), "name": s.name} for s in row.expected_but_never_ran],
    }


class ProjectHealthService:
    def _project(self, tenant: Tenant, project_id: str) -> Project:
        try:
            return Project.objects.select_related("platform_connection", "tenant").get(
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
        """The project's health — its score, the newest scored commit on the
        default branch — or, with ``branch``, that branch's. ``newer_commit``
        is a newer commit with no verdict: still checking, or no score."""
        project = self._project(tenant, project_id)
        on = branch or project.default_branch
        score = scoring.branch_score(project, on)
        results = (
            sorted(score.executions.select_related("commit_check"), key=lambda ex: ex.created_at, reverse=True)
            if score
            else []
        )
        newer = scoring.newer_commit(project, on, score)
        return {
            "project": {"id": str(project.id), "name": project.name},
            "branch": branch or None,
            "default_branch": project.default_branch,
            **_summary(project, score, results),
            "commit_score": (
                _commit_score(project, score.commit_sha, on, _verdict_standing(score), score.committed_at)
                if score
                else None
            ),
            "newer_commit": (
                {
                    "sha": newer.sha,
                    "outcome": str(newer.standing.outcome),
                    "reason": newer.standing.reason,
                    "standards": {
                        "expected": newer.standing.expected_count,
                        "finished": newer.standing.finished_count,
                    },
                }
                if newer
                else None
            ),
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
            "commits": [_commit(project, row, branch) for row in rows],
        }

    def commit(self, tenant: Tenant, project_id: str, sha: str) -> dict:
        """One commit's checks, from what GitGrit recorded."""
        project = self._project(tenant, project_id)
        row = commit_checks.commit_results(project, sha)
        if not row.checked:
            raise NotFoundError(f"No checks recorded for commit {sha}")
        return _commit(project, row, scoring.commit_branch(project, sha, row.commit_score))

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
