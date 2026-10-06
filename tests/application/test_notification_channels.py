"""Channels: the inbox repeat rule must replace unread copies and keep read ones."""

import threading

from django.db import connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone
from model_bakery import baker

from app.application.notifications.channels import (
    InboxChannel,
    LogChannel,
    channel_for,
)
from app.domain.models import NotificationDelivery
from app.domain.notifications import Notice, Severity


def _notice(tenant, dedupe_key=None):
    return Notice(
        kind="run.failed",
        tenant_id=str(tenant.pk),
        severity=Severity.CRITICAL,
        title="Run failed",
        body="",
        url="/x",
        dedupe_key=dedupe_key,
    )


class InboxChannelTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.alice = baker.make("app.User")
        self.bob = baker.make("app.User")

    def _notification(self, key=""):
        return baker.make("app.Notification", tenant=self.tenant, dedupe_key=key)

    def test_writes_one_sent_row_per_recipient(self):
        notification = self._notification()

        InboxChannel().deliver(
            _notice(self.tenant), str(notification.pk), [str(self.alice.pk), str(self.bob.pk)]
        )

        rows = NotificationDelivery.objects.filter(notification=notification)
        self.assertEqual(rows.count(), 2)
        for row in rows:
            self.assertEqual(row.channel, "inbox")
            self.assertEqual(row.status, "sent")
            self.assertIsNotNone(row.sent_at)

    def test_dedupe_replaces_unread_keeps_read_and_other_recipients(self):
        old = self._notification("k")
        old_unread = baker.make(
            "app.NotificationDelivery", notification=old, channel="inbox", recipient=self.alice
        )
        old_read = baker.make(
            "app.NotificationDelivery",
            notification=old,
            channel="inbox",
            recipient=self.alice,
            read_at=timezone.now(),
        )
        bobs = baker.make(
            "app.NotificationDelivery", notification=old, channel="inbox", recipient=self.bob
        )
        new = self._notification("k")

        InboxChannel().deliver(_notice(self.tenant, "k"), str(new.pk), [str(self.alice.pk)])

        self.assertFalse(NotificationDelivery.objects.filter(pk=old_unread.pk).exists())
        self.assertTrue(NotificationDelivery.objects.filter(pk=old_read.pk).exists())
        self.assertTrue(NotificationDelivery.objects.filter(pk=bobs.pk).exists())
        self.assertEqual(
            NotificationDelivery.objects.filter(notification=new, recipient=self.alice).count(), 1
        )


class InboxChannelPinTests(TestCase):
    def test_dedupe_keeps_a_pinned_unread_copy(self):
        tenant = baker.make("app.Tenant")
        alice = baker.make("app.User")
        old = baker.make("app.Notification", tenant=tenant, dedupe_key="k")
        pinned = baker.make(
            "app.NotificationDelivery",
            notification=old,
            channel="inbox",
            recipient=alice,
            pinned_at=timezone.now(),
        )
        new = baker.make("app.Notification", tenant=tenant, dedupe_key="k")

        InboxChannel().deliver(_notice(tenant, "k"), str(new.pk), [str(alice.pk)])

        self.assertTrue(NotificationDelivery.objects.filter(pk=pinned.pk).exists())
        self.assertEqual(NotificationDelivery.objects.filter(recipient=alice).count(), 2)


class InboxChannelRaceTests(TransactionTestCase):
    """Two deliveries with one dedupe key at the same time must not leave two
    unread copies. Real threads and real connections: the repeat rule is a
    delete-then-insert, and under READ COMMITTED a second DELETE that started
    before the first INSERT committed cannot see it."""

    ROUNDS = 5

    def test_concurrent_deliveries_leave_one_unread_copy(self):
        tenant = baker.make("app.Tenant")
        alice = baker.make("app.User")
        for _ in range(self.ROUNDS):
            rows = [baker.make("app.Notification", tenant=tenant, dedupe_key="k") for _ in range(2)]
            barrier = threading.Barrier(2)
            errors = []

            def deliver(notification):
                try:
                    barrier.wait(timeout=5)
                    InboxChannel().deliver(_notice(tenant, "k"), str(notification.pk), [str(alice.pk)])
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)
                finally:
                    connections.close_all()

            threads = [threading.Thread(target=deliver, args=(row,)) for row in rows]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            self.assertEqual(errors, [])
            unread = NotificationDelivery.objects.filter(
                recipient=alice, read_at__isnull=True, notification__dedupe_key="k"
            )
            self.assertEqual(unread.count(), 1, "the repeat rule let two unread copies through")
            unread.delete()


class LogChannelTests(SimpleTestCase):
    def test_logs_one_info_line(self):
        tenant = baker.prepare("app.Tenant", id="t1")

        with self.assertLogs("app.application.notifications.channels", "INFO") as logs:
            LogChannel().deliver(_notice(tenant), "n1", ["u1", "u2"])

        self.assertEqual(len(logs.records), 1)
        self.assertIn("run.failed", logs.output[0])
        self.assertIn("recipients=2", logs.output[0])


class ChannelForTests(SimpleTestCase):
    def test_known_names_resolve(self):
        self.assertEqual(channel_for("inbox").name, "inbox")
        self.assertEqual(channel_for("log").name, "log")

    def test_unknown_name_raises_key_error(self):
        with self.assertRaises(KeyError):
            channel_for("x")
