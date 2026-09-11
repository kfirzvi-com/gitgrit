from __future__ import annotations

from app.domain.events import DomainEvent
from app.infrastructure.parsers.base import BaseWebhookParser

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
        )
