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


# The "after" SHA GitHub sends when a push deletes its branch: no commit exists.
NULL_SHA = "0" * 40


def commit_sha_for(event_type: str, payload: dict) -> str | None:
    """The commit a GitHub event is about, or None when there is none."""
    if event_type == "push":
        sha = payload.get("after")
        return sha if sha and sha != NULL_SHA else None
    if event_type == "pull_request":
        return (payload.get("pull_request") or {}).get("head", {}).get("sha") or None
    return None


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
            commit_sha=commit_sha_for(event_type, payload),
            actor=sender.get("login"),
            raw_payload=payload,
        )
