from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DomainEvent:
    event_type: str  # "push", "merge_request", etc.
    platform: str  # "github" | "gitlab"
    external_project_id: str  # platform's project/repo ID as string
    ref: str | None = None
    actor: str | None = None
    raw_payload: dict = field(default_factory=dict)
