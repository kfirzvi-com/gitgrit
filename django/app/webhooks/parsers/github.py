from __future__ import annotations

from app.domain.events import DomainEvent
from app.webhooks.parsers.base import BaseWebhookParser

# Map GitHub event names to canonical event types.
GITHUB_EVENT_MAP = {
    "push": "push",
    "pull_request": "merge_request",
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

        return DomainEvent(
            event_type=event_type,
            platform="github",
            external_project_id=str(repository.get("id", "")),
            ref=payload.get("ref"),
            actor=sender.get("login"),
            raw_payload=payload,
        )
