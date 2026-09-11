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
        )
