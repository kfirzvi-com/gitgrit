"""Channels: how a notification reaches people.

``Channel`` is the port: anything with a ``name`` and
``deliver(notification, recipient_ids)``. Notification routing names the
channels each kind goes to. ``InboxChannel`` is the one adapter today; it
only touches the domain's own Inbox, so it lives here. Adapters that talk to
outside systems (email, GitHub Checks) belong in ``app.infrastructure``, and
the dispatcher's registry plugs them in.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.models import Notification
from app.domain.notifications.inbox import Inbox


class Channel(Protocol):
    name: str

    def deliver(self, notification: Notification, recipient_ids: list[str]) -> None: ...


class InboxChannel:
    """Puts the notification in each recipient's inbox."""

    name = "inbox"

    def deliver(self, notification: Notification, recipient_ids: list[str]) -> None:
        for user_id in recipient_ids:
            Inbox(user_id, notification.tenant_id).receive(notification)
