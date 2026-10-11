"""Commit checks: which commit each run checked, and a branch's history of
commits with the standards GitGrit ran on each.

The project page reads a branch's commits from the Git platform (every
commit, checked or not) and lays the checks over them. Platform calls are
best-effort: when the platform cannot be reached, the history falls back to
what GitGrit recorded itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from django.utils.dateparse import parse_datetime

from app.application.standard_engine import StandardEngine
from app.application.standard_results import current_results, project_score
from app.domain.models import CommitCheck, StandardExecution

logger = logging.getLogger(__name__)

Status = StandardExecution.Status
COMMITS_PER_PAGE = 5


# --- Talking to the Git platform --------------------------------------------------


def _client(project):
    from app.infrastructure.platform_client import get_platform_client

    return get_platform_client(project.platform_connection)


def resolve_head_commit(project, branch: str) -> dict:
    """``branch``'s latest commit as ``{sha, date}``, or {} when the platform
    cannot say (unreachable, no such branch)."""
    try:
        return _client(project).head_commit(project.external_id, project.full_path, branch) or {}
    except Exception:
        logger.warning("Could not resolve the head of %s on %s", branch, project.name, exc_info=True)
        return {}


def pin_head_commits(project, executions) -> None:
    """Pin each check of these runs that was queued without a commit (a
    manual or coverage-change run) to its branch's head commit, before the
    runs read the repository. A check the platform cannot resolve stays
    unpinned and its runs read the branch."""
    checks = {e.commit_check for e in executions if e.commit_check and not e.commit_check.commit_sha}
    for check in checks:
        head = resolve_head_commit(project, check.branch)
        if head.get("sha"):
            CommitCheck.objects.filter(pk=check.pk, commit_sha="").update(
                commit_sha=head["sha"],
                committed_at=parse_datetime(head["date"]) if head.get("date") else None,
            )


# --- A branch's history -------------------------------------------------------------


@dataclass
class CommitRow:
    """One commit on a branch, with the latest result of each standard GitGrit
    ran on it (empty when it was never checked)."""

    sha: str
    message: str = ""
    author: str = ""
    date: datetime | None = None
    url: str = ""
    results: list = field(default_factory=list)
    # Current standards that apply to the branch but did not run on this
    # commit (attached since, or skipped). Only filled for checked commits.
    not_run: list = field(default_factory=list)

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    @property
    def title(self) -> str:
        return (self.message or "").splitlines()[0] if self.message else ""

    @property
    def checked(self) -> bool:
        return bool(self.results)

    def _count(self, status) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def passed(self) -> int:
        return self._count(Status.PASSED)

    @property
    def failed(self) -> int:
        return self._count(Status.FAILED)

    @property
    def errored(self) -> int:
        return self._count(Status.ERROR)

    @property
    def running(self) -> int:
        return self._count(Status.RUNNING)

    @property
    def score(self) -> int | None:
        return project_score([r for r in self.results if r.status != Status.RUNNING])


def branches(project) -> list[str]:
    """Every branch of the project's repository, the default branch first.
    Falls back to the branches GitGrit has checked when the platform cannot
    be reached."""
    try:
        names = _client(project).list_branches(project.external_id, project.full_path)
    except Exception:
        logger.warning("Could not list branches of %s", project.name, exc_info=True)
        names = list(
            CommitCheck.objects.filter(project=project).values_list("branch", flat=True).distinct()
        )
    others = sorted(n for n in set(names) if n != project.default_branch)
    return [project.default_branch, *others]


def branch_commits(project, branch: str, page: int = 1) -> tuple[list[CommitRow], bool]:
    """One page of ``branch``'s commits, newest first, each with the results
    of the standards GitGrit ran on it; and whether there are older commits.
    Falls back to the commits GitGrit checked on the branch when the platform
    cannot be reached."""
    try:
        listed = _client(project).list_commits(
            project.external_id, project.full_path, branch, page=page, per_page=COMMITS_PER_PAGE
        )
        rows = [
            CommitRow(
                sha=c["sha"],
                message=c.get("message", ""),
                author=c.get("author", ""),
                date=parse_datetime(c["date"]) if c.get("date") else None,
                url=c.get("url", ""),
            )
            for c in listed
        ]
        has_more = len(listed) == COMMITS_PER_PAGE
    except Exception:
        logger.warning("Could not list commits of %s on %s", branch, project.name, exc_info=True)
        rows, has_more = _checked_commits(project, branch, page)
    _attach_results(project, rows, applicable=StandardEngine().standards_for_branch(project, branch))
    return rows, has_more


def branch_status(project, branch: str) -> list:
    """The latest finished result of each attached standard on ``branch``."""
    return current_results([project], branch=branch)


def earlier_runs(project, branch: str, limit: int = 20) -> list:
    """Runs on ``branch`` recorded before commit checks existed (no commit)."""
    refs = {branch, f"refs/heads/{branch}"}
    if branch == project.default_branch:
        refs.add("")
    return list(
        StandardExecution.objects.filter(project=project, commit_check__isnull=True, ref__in=refs)
        .order_by("-created_at")[:limit]
    )


def _checked_commits(project, branch, page):
    shas = list(
        dict.fromkeys(
            CommitCheck.objects.filter(project=project, branch=branch)
            .exclude(commit_sha="")
            .order_by("-created_at")
            .values_list("commit_sha", flat=True)
        )
    )
    start = (page - 1) * COMMITS_PER_PAGE
    window = shas[start : start + COMMITS_PER_PAGE]
    return [CommitRow(sha=sha) for sha in window], len(shas) > start + COMMITS_PER_PAGE


def _attach_results(project, rows, applicable=()) -> None:
    """Give each commit the latest result per standard across its checks.
    Standards attach and detach over time, so a commit's results are the
    standards that ran on it then: each result says whether its standard is
    still attached, and a checked commit lists the current standards that
    did not run on it."""
    by_sha = {row.sha: row for row in rows}
    if not by_sha:
        return
    attached = set(project.standards.values_list("pk", flat=True))
    seen = set()
    executions = (
        StandardExecution.objects.filter(project=project, commit_check__commit_sha__in=by_sha)
        .select_related("commit_check", "standard_version")
        .order_by("-created_at")
    )
    for ex in executions:
        key = (ex.commit_check.commit_sha, ex.standard_id)
        if key in seen:
            continue
        seen.add(key)
        ex.still_attached = ex.standard_id in attached
        by_sha[ex.commit_check.commit_sha].results.append(ex)
    for row in rows:
        if row.results:
            ran = {r.standard_id for r in row.results}
            row.not_run = [s for s in applicable if s.pk not in ran]
