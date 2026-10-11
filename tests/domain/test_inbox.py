"""The Inbox and its reading rules."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.domain.notifications.inbox import Inbox
from app.domain.models import InboxItem, Notification


class InboxTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.user = baker.make("app.User")
        self.inbox = Inbox(self.user.pk, self.tenant.pk)

    def _notification(self, tenant=None, title="Something"):
        return baker.make("app.Notification", tenant=tenant or self.tenant, title=title, kind="k")

    def _item(self, title="Something", read=False, user=None, tenant=None, ago=None):
        notification = self._notification(tenant=tenant, title=title)
        if ago is not None:
            Notification.objects.filter(pk=notification.pk).update(created_at=timezone.now() - ago)
        return baker.make(
            "app.InboxItem", notification=notification, recipient=user or self.user,
            read_at=timezone.now() if read else None,
        )

    # --- receive ---------------------------------------------------------------

    def test_receive_adds_an_unread_item(self):
        item = self.inbox.receive(self._notification())

        self.assertTrue(item.is_unread)
        self.assertEqual(self.inbox.unread_count(), 1)

    def test_receive_refuses_another_workspaces_notification(self):
        with self.assertRaises(ValueError):
            self.inbox.receive(self._notification(tenant=baker.make("app.Tenant")))
        self.assertFalse(InboxItem.objects.exists())

    # --- reading -------------------------------------------------------------

    def test_mark_read_moves_an_item_to_history_and_keeps_the_first_read_time(self):
        item = self._item()

        first = self.inbox.mark_read(item.pk).read_at
        again = self.inbox.mark_read(item.pk).read_at

        self.assertIsNotNone(first)
        self.assertEqual(first, again)
        self.assertEqual(self.inbox.active(), [])
        self.assertEqual([i.pk for i in self.inbox.history()], [item.pk])

    def test_mark_read_of_someone_elses_item_is_not_found(self):
        item = self._item(user=baker.make("app.User"))

        with self.assertRaises(InboxItem.DoesNotExist):
            self.inbox.mark_read(item.pk)
        item.refresh_from_db()
        self.assertIsNone(item.read_at)

    def test_reading_is_personal(self):
        colleague = baker.make("app.User")
        notification = self._notification()
        mine = Inbox(self.user.pk, self.tenant.pk).receive(notification)
        theirs = Inbox(colleague.pk, self.tenant.pk).receive(notification)

        self.inbox.mark_read(mine.pk)

        theirs.refresh_from_db()
        self.assertTrue(theirs.is_unread)

    def test_mark_all_read_only_touches_my_unread_in_this_workspace(self):
        self._item("a")
        self._item("b")
        other_user = self._item("c", user=baker.make("app.User"))
        other_tenant = self._item("d", tenant=baker.make("app.Tenant"))

        self.assertEqual(self.inbox.mark_all_read(), 2)

        self.assertEqual(self.inbox.unread_count(), 0)
        for item in (other_user, other_tenant):
            item.refresh_from_db()
            self.assertTrue(item.is_unread)

    # --- reads ---------------------------------------------------------------

    def test_active_and_history_are_newest_first(self):
        self._item("old", ago=timedelta(days=2))
        self._item("new")
        self._item("read-old", read=True, ago=timedelta(days=2))
        self._item("read-new", read=True)

        self.assertEqual([i.notification.title for i in self.inbox.active()], ["new", "old"])
        self.assertEqual(
            [i.notification.title for i in self.inbox.history()], ["read-new", "read-old"]
        )

    def test_history_is_limited(self):
        for i in range(3):
            self._item(f"read-{i}", read=True)
        self.assertEqual(len(self.inbox.history(limit=2)), 2)

    def test_an_inbox_without_a_workspace_is_empty(self):
        self._item()
        inbox = Inbox(self.user.pk, None)

        self.assertEqual(inbox.unread_count(), 0)
        self.assertEqual(inbox.active(), [])
        self.assertEqual(inbox.mark_all_read(), 0)
