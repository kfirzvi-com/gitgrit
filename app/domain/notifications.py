"""Domain types for the notification center.

Two ideas shape this module. A Notice is facts about something that happened,
not a message addressed to a person. Routing (who hears it, through which
channel) is policy and lives in one place, expressed with Audience and Rule.
Pure dataclasses: no Django imports, so any layer can build a Notice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Audience:
    """Describes recipients without resolving them to users."""

    roles: tuple[str, ...] = ()
    user_ids: tuple[str, ...] = ()

    @classmethod
    def team(cls) -> Audience:
        return cls(roles=("owner", "admin", "member"))

    @classmethod
    def admins(cls) -> Audience:
        return cls(roles=("owner", "admin"))

    @classmethod
    def users(cls, *user_ids: str) -> Audience:
        return cls(user_ids=tuple(user_ids))


@dataclass(frozen=True)
class Notice:
    """What happened. Named Notice so it does not clash with the Notification model."""

    kind: str
    tenant_id: str
    severity: Severity
    title: str
    body: str
    url: str
    context: dict = field(default_factory=dict)  # ids only
    dedupe_key: str | None = None
    mentioned_user_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    """Who should know about a kind of notice, and how they hear it."""

    audience: Audience
    channels: tuple[str, ...]


class Channel(Protocol):
    name: str

    def deliver(
        self, notice: Notice, notification_id: str, recipient_ids: list[str]
    ) -> None: ...
