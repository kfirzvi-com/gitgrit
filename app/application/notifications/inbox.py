"""The Inbox: one person's notifications in one workspace.

The aggregate root over ``InboxItem`` rows. It owns the reading rules:

* every notification delivered to a person becomes its own item (repeats are
  not merged here; grouping, if ever, belongs in the notification policies so
  every channel gets it);
* an item is Active until its recipient reads it, by opening it, marking it
  read, or marking everything read; read items are History;
* reading is personal: one person reading an item never changes anyone
  else's copy;
* an inbox only holds notifications from its own workspace.
"""

from __future__ import annotations

from django.utils import timezone

from app.domain.models import InboxItem, Notification

HISTORY_LIMIT = 50


class Inbox:
    def __init__(self, user_id, tenant_id):
        self.user_id = user_id
        self.tenant_id = tenant_id

    # --- Commands ------------------------------------------------------------

    def receive(self, notification: Notification) -> InboxItem:
        """Add a delivered notification as a new, unread item."""
        if str(notification.tenant_id) != str(self.tenant_id):
            raise ValueError("A notification can only go to an inbox in its own workspace.")
        return InboxItem.objects.create(notification=notification, recipient_id=self.user_id)

    def mark_read(self, item_id) -> InboxItem:
        """Read one item (by opening it or with Mark read). Reading an item
        that is already read keeps its first read time. Raises
        ``InboxItem.DoesNotExist`` for an item that is not in this inbox."""
        item = self._items().select_related("notification").get(pk=item_id)
        if item.is_unread:
            item.read_at = timezone.now()
            item.save(update_fields=["read_at"])
        return item

    def mark_all_read(self) -> int:
        """Read every Active item; returns how many."""
        return self._items().filter(read_at__isnull=True).update(read_at=timezone.now())

    # --- Reads ---------------------------------------------------------------

    def unread_count(self) -> int:
        return self._items().filter(read_at__isnull=True).count()

    def active(self) -> list[InboxItem]:
        """Unread items, newest first."""
        return list(
            self._items()
            .filter(read_at__isnull=True)
            .select_related("notification")
            .order_by("-notification__created_at")
        )

    def history(self, limit: int = HISTORY_LIMIT) -> list[InboxItem]:
        """Read items, newest first."""
        return list(
            self._items()
            .filter(read_at__isnull=False)
            .select_related("notification")
            .order_by("-notification__created_at")[:limit]
        )

    def _items(self):
        if self.user_id is None or self.tenant_id is None:
            return InboxItem.objects.none()
        return InboxItem.objects.filter(
            recipient_id=self.user_id, notification__tenant_id=self.tenant_id
        )
