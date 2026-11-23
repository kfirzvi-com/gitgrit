from __future__ import annotations

from app.domain.events import DomainEvent
from app.infrastructure.parsers.base import BaseWebhookParser

# A push's ``after`` when the push deleted the branch or tag.
DELETED_SHA = "0" * 40

# Map GitLab event names to canonical event types (the names standards use).
GITLAB_EVENT_MAP = {
    "merge_request": "pull_request",
}


class GitLabParser(BaseWebhookParser):
    def parse(self, headers: dict, payload: dict) -> DomainEvent:
        gitlab_event = payload.get("event_name") or payload.get("object_kind", "")
        event_type = GITLAB_EVENT_MAP.get(gitlab_event, gitlab_event)
        attributes = payload.get("object_attributes") or {}

        project = payload.get("project", {})
        external_project_id = str(
            payload.get("project_id") or project.get("id", "")
        )

        actor = payload.get("user_username") or payload.get("user", {}).get(
            "username"
        )

        return DomainEvent(
            event_type=event_type,
            platform="gitlab",
            external_project_id=external_project_id,
            # push/tag_push carry a top-level ref. A merge request carries its
            # source branch (what the run reads) and target branch (what the
            # Branch/Tag Filter matches) under object_attributes.
            ref=payload.get("ref") or attributes.get("source_branch"),
            target_ref=attributes.get("target_branch"),
            actor=actor,
            raw_payload=payload,
            deleted=payload.get("after") == DELETED_SHA,
            commit_sha=(attributes.get("last_commit") or {}).get("id")
            or payload.get("checkout_sha")
            or payload.get("after")
            or "",
            committed_at=(attributes.get("last_commit") or {}).get("timestamp")
            or next(
                (c.get("timestamp", "") for c in payload.get("commits") or [] if c.get("id") == payload.get("checkout_sha")),
                "",
            ),
            changed_paths=_pushed_paths(payload) if event_type == "push" else None,
            base_sha=_real_sha(payload.get("before"))
            or (attributes.get("diff_refs") or {}).get("base_sha", ""),
        )


def _real_sha(sha: str | None) -> str:
    return "" if not sha or sha == DELETED_SHA else sha


def _pushed_paths(payload: dict) -> tuple[str, ...] | None:
    """Every path a push's commits added, changed or removed, or None when the
    payload can't say for sure: a new branch, or more commits than it lists
    (GitLab lists 20; ``total_commits_count`` says how many there were)."""
    commits = payload.get("commits")
    if not isinstance(commits, list) or payload.get("before") == DELETED_SHA:
        return None
    if (payload.get("total_commits_count") or len(commits)) > len(commits):
        return None
    paths: set[str] = set()
    for commit in commits:
        for key in ("added", "modified", "removed"):
            paths.update(commit.get(key) or [])
    return tuple(sorted(paths))
