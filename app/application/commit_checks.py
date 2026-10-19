"""Commit checks: which commit each run checked, and a branch's history of
commits with the standards GitGrit ran on each.

The project page reads a branch's commits from the Git platform (every
commit, checked or not) and lays the checks over them. Platform calls are
best-effort: when the platform cannot be reached, the history falls back to
what GitGrit recorded itself.

The page re-renders every few seconds while runs are in flight, so the
platform's branch and commit lists are cached for a minute (only what the
platform answered; never a fallback). A push webhook clears a project's
cache, so a new commit shows up at once.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime

from django.core.cache import caches
from django.utils.dateparse import parse_datetime

from app.application.standard_engine import StandardEngine
from app.application.scoring import commit_branch, commit_history
from app.domain.scoring import CommitScoreOutcome
from app.application.standard_results import current_results
from app.domain.models import CommitCheck, Standard, StandardExecution

logger = logging.getLogger(__name__)

Status = StandardExecution.Status
COMMITS_PER_PAGE = 5
PLATFORM_LISTS_TTL = 60  # seconds


# --- Talking to the Git platform --------------------------------------------------


def _client(project):
    from app.infrastructure.platform_client import get_platform_client

    return get_platform_client(project.platform_connection)


def _generation_key(project) -> str:
    return f"platform-lists:{project.pk}:generation"


def _cached(project, name: str, fetch):
    """``fetch()``'s answer, cached per project for PLATFORM_LISTS_TTL.
    ``fetch`` raising is not cached: the caller falls back and the next
    render asks the platform again."""
    cache = caches["platform"]
    generation = cache.get_or_set(_generation_key(project), 0, timeout=None)
    key = f"platform-lists:{project.pk}:{generation}:{hashlib.sha256(name.encode()).hexdigest()[:24]}"
    value = cache.get(key)
    if value is None:
        value = fetch()
        cache.set(key, value, PLATFORM_LISTS_TTL)
    return value


def forget_platform_lists(projects) -> None:
    """Drop what the project page cached from the platform for these
    projects (a push moved a branch, or added or deleted one)."""
    cache = caches["platform"]
    for project in projects:
        try:
            cache.incr(_generation_key(project))
        except ValueError:
            cache.set(_generation_key(project), 1, timeout=None)


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


@dataclass
class BranchRun:
    """What ``run_on_branch`` queued: the commit it pinned ("" when the job
    will pin the branch's head), the enqueue summary (None when no standard
    applies to the branch) and a sentence saying so."""

    branch: str
    commit_sha: str
    summary: dict | None
    notice: str


def run_on_branch(project, branch: str, *, sha: str = "", committed_at=None, user=None) -> BranchRun:
    """Run the project's current standards that apply to ``branch``: on one
    commit (``sha``), or on the branch's latest commit, pinned now so the
    commit shows its runs at once. If the platform cannot say what the head
    is, the job pins it."""
    from app.application.standard_runs import enqueue_run

    target = sha[:7] if sha else f"the latest commit on {branch}"
    if project.is_upload and not sha and not project.upload_commits.filter(branch=branch).exists():
        # Nothing uploaded to this branch: no files a run could read.
        return BranchRun(
            branch=branch, commit_sha="", summary=None,
            notice=f"No commit has been uploaded to {branch} yet.",
        )
    if not sha:
        head = resolve_head_commit(project, branch)
        sha = head.get("sha", "")
        committed_at = parse_datetime(head["date"]) if head.get("date") else None
        if sha:
            target = f"{sha[:7]}, the latest commit on {branch}"
    standards = StandardEngine().standards_for_branch(project, branch)
    summary = enqueue_run(
        project,
        standards,
        triggered_by="manual",
        user=user,
        ref=branch,
        commit_sha=sha,
        committed_at=committed_at,
    )
    if summary is None:
        notice = f"No standards apply to {branch}."
    elif summary["queued"]:
        notice = f"Running {summary['queued']} standard{'s' if summary['queued'] != 1 else ''} on {target}."
    else:
        notice = "Those standards are already running."
    return BranchRun(branch=branch, commit_sha=sha, summary=summary, notice=notice)


# --- A branch's history -------------------------------------------------------------


@dataclass
class CommitRow:
    """One commit on a branch: every run of the standards on it (``checks``,
    oldest first: the Results tab's timeline) and the one it reads, its
    newest (``shown``), with that run's result of each standard (empty when
    it was never checked)."""

    sha: str
    message: str = ""
    author: str = ""
    date: datetime | None = None
    url: str = ""
    # The branch its runs are read on.
    branch: str = ""
    # The runs of the standards on it (``scoring.CheckRunRecord``), oldest first.
    checks: list = field(default_factory=list)
    # The run the Results tab's timeline shows (a check id); its newest when
    # None.
    selected_id: object = None

    @property
    def shown(self):
        """The run the commit reads: its newest."""
        return self.checks[-1] if self.checks else None

    @property
    def selected_index(self) -> int:
        """Where the timeline's selected run is among ``checks`` (0-based)."""
        for i, run in enumerate(self.checks):
            if run.check.pk == self.selected_id:
                return i
        return len(self.checks) - 1

    @property
    def selected(self):
        """The run the timeline shows: ``selected_id``'s, else the newest."""
        return self.checks[self.selected_index] if self.checks else None

    @property
    def previous_check(self):
        """The run before the selected one, if any."""
        i = self.selected_index
        return self.checks[i - 1] if self.checks and i > 0 else None

    @property
    def next_check(self):
        """The run after the selected one, if any."""
        i = self.selected_index
        return self.checks[i + 1] if self.checks and i + 1 < len(self.checks) else None

    @property
    def results(self) -> list:
        """The newest run's result of each standard it expected."""
        return self.shown.latest_runs if self.shown else []

    @property
    def expected_but_never_ran(self) -> list:
        """The standards the newest run expected that never ran in it
        (``CheckRunRecord.never_ran``): why the commit may have no score."""
        return list(self.shown.never_ran) if self.shown else []

    @property
    def commit_score(self):
        """The score the newest run saved (None while it runs)."""
        return self.shown.score if self.shown else None

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    @property
    def title(self) -> str:
        return (self.message or "").splitlines()[0] if self.message else ""

    @property
    def checked(self) -> bool:
        return bool(self.checks)

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
        return self.commit_score.value if self.commit_score else None

    @property
    def outcome(self) -> CommitScoreOutcome | None:
        """The commit's one outcome: its newest run's."""
        return self.shown.outcome if self.shown else None

    @property
    def scored(self) -> bool:
        """It has a verdict to show: an F or a number."""
        return self.outcome is not None and self.outcome.is_verdict

    @property
    def failed_score(self) -> bool:
        return bool(self.commit_score and self.commit_score.failed)


def branches(project) -> list[str]:
    """Every branch of the project's repository, the default branch first.
    Falls back to the branches GitGrit has checked when the platform cannot
    be reached."""
    try:
        names = _cached(
            project, "branches",
            lambda: _client(project).list_branches(project.external_id, project.full_path),
        )
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
        listed = _cached(
            project, f"commits:{page}:{branch}",
            lambda: _client(project).list_commits(
                project.external_id, project.full_path, branch, page=page, per_page=COMMITS_PER_PAGE
            ),
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
    _attach_checks(project, rows, branch)
    return rows, has_more


def branch_status(project, branch: str) -> list:
    """The latest finished result of each attached standard on ``branch``."""
    return current_results([project], branch=branch)


def commit_results(project, sha: str) -> CommitRow:
    """One commit's runs from what GitGrit recorded (no platform call), on
    the branch it is read on (``scoring.commit_branch``, ``row.branch``)."""
    row = CommitRow(sha=sha, branch=commit_branch(project, sha, None))
    _attach_checks(project, [row], row.branch)
    return row


def commit_runs(project, check_id) -> CommitRow | None:
    """The commit of one of the project's checks, with every run on it on
    that check's branch, that check selected (the Results tab's timeline).
    None when the check is not the project's."""
    check = CommitCheck.objects.filter(project=project, pk=check_id).exclude(commit_sha="").first()
    if check is None:
        return None
    row = CommitRow(sha=check.commit_sha, branch=check.branch, selected_id=check.pk)
    _attach_checks(project, [row], check.branch)
    return row


def waiting_for_commit(project, branch: str) -> bool:
    """Whether runs on ``branch`` are in flight before their job has pinned
    their commit (they belong to no commit row yet)."""
    return StandardExecution.objects.filter(
        project=project, status=Status.RUNNING, commit_check__branch=branch, commit_check__commit_sha=""
    ).exists()


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


def _attach_checks(project, rows, branch: str) -> None:
    """Give each commit its runs on ``branch`` (``scoring.commit_history``),
    each result saying whether its standard is still attached and each run
    naming the standards it expected that never ran in it (``never_ran``)."""
    if not rows:
        return
    history = commit_history(project, [row.sha for row in rows], branch=branch)
    attached = set(project.standards.values_list("pk", flat=True))
    runs = [run for row in rows for run in history.get(row.sha, [])]
    # One query for the standards' names (archived ones included).
    never_ran_ids = {i for run in runs for i in run.never_ran_ids}
    standards = (
        {str(s.pk): s for s in Standard.all_objects.filter(pk__in=never_ran_ids)} if never_ran_ids else {}
    )
    for run in runs:
        for ex in run.executions:
            ex.still_attached = ex.standard_id in attached
    for row in rows:
        row.checks = [
            replace(run, never_ran=tuple(standards[i] for i in run.never_ran_ids if i in standards))
            for run in history.get(row.sha, [])
        ]
