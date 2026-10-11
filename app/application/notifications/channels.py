"""Channels: how a notification reaches people.

A channel is anything with a ``name`` and ``deliver(notification,
recipient_ids)``. Today there is one, the inbox; email or GitHub Checks would
each be one more class here plus a name in a route.
"""

from __future__ import annotations

from typing import Protocol

from app.application.notifications.inbox import Inbox
from app.domain.models import Notification


class Channel(Protocol):
    name: str

    def deliver(self, notification: Notification, recipient_ids: list[str]) -> None: ...


class InboxChannel:
    """Puts the notification in each recipient's inbox."""

    name = "inbox"

    def deliver(self, notification: Notification, recipient_ids: list[str]) -> None:
        for user_id in recipient_ids:
            Inbox(user_id, notification.tenant_id).receive(notification)


CHANNELS: dict[str, Channel] = {c.name: c for c in (InboxChannel(),)}


def channel_for(name: str) -> Channel:
    try:
        return CHANNELS[name]
    except KeyError:
        raise KeyError(
            f"Unknown notification channel {name!r}; known: {sorted(CHANNELS)}"
        ) from None
