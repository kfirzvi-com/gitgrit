from __future__ import annotations

from app.domain.events import DomainEvent
from app.infrastructure.parsers.base import BaseWebhookParser


class GitLabParser(BaseWebhookParser):
    def parse(self, headers: dict, payload: dict) -> DomainEvent:
        event_type = payload.get("event_name") or payload.get("object_kind", "")

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
            ref=payload.get("ref"),
            actor=actor,
            raw_payload=payload,
        )
