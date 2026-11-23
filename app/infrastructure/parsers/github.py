from __future__ import annotations

from app.domain.events import DomainEvent
from app.infrastructure.parsers.base import BaseWebhookParser

# Map GitHub event names to canonical event types.
GITHUB_EVENT_MAP = {
    "push": "push",
    "pull_request": "pull_request",
    "create": "create",
    "delete": "delete",
    "release": "release",
    "issues": "issues",
    "issue_comment": "issue_comment",
}


class GitHubParser(BaseWebhookParser):
    def parse(self, headers: dict, payload: dict) -> DomainEvent:
        github_event = headers.get("x-github-event", "")
        event_type = GITHUB_EVENT_MAP.get(github_event, github_event)

        repository = payload.get("repository", {})
        sender = payload.get("sender", {})
        pull_request = payload.get("pull_request") or {}

        return DomainEvent(
            event_type=event_type,
            platform="github",
            external_project_id=str(repository.get("id", "")),
            # push/create/delete carry a top-level ref. A pull_request carries
            # its source branch under head (what the run reads) and its target
            # branch under base (what the Branch/Tag Filter matches).
            ref=payload.get("ref") or pull_request.get("head", {}).get("ref"),
            target_ref=pull_request.get("base", {}).get("ref"),
            actor=sender.get("login"),
            raw_payload=payload,
            deleted=payload.get("deleted") is True,
            commit_sha=pull_request.get("head", {}).get("sha") or payload.get("after") or "",
            committed_at=(payload.get("head_commit") or {}).get("timestamp", ""),
            changed_paths=_pushed_paths(payload) if event_type == "push" else None,
            base_sha=pull_request.get("base", {}).get("sha") or _real_sha(payload.get("before")),
        )


# GitHub lists at most this many commits in a push payload; a push with more
# is listed partially, so its file lists can't be trusted.
MAX_LISTED_COMMITS = 2048
_NO_COMMIT = "0" * 40


def _real_sha(sha: str | None) -> str:
    return "" if not sha or sha == _NO_COMMIT else sha


def _pushed_paths(payload: dict) -> tuple[str, ...] | None:
    """Every path a push's commits added, changed or removed, or None when the
    payload can't say for sure: a new branch (its commits are listed relative
    to nothing), a force push (commits were dropped too), or a truncated list."""
    commits = payload.get("commits")
    if (
        not isinstance(commits, list)
        or payload.get("created")
        or payload.get("forced")
        or len(commits) >= MAX_LISTED_COMMITS
    ):
        return None
    paths: set[str] = set()
    for commit in commits:
        for key in ("added", "modified", "removed"):
            paths.update(commit.get(key) or [])
    return tuple(sorted(paths))
