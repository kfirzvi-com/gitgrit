"""Channels: the inbox writes one row per recipient and never replaces earlier ones."""

from django.test import SimpleTestCase, TestCase
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

    def test_same_key_adds_a_new_copy_and_keeps_the_old_one(self):
        """A repeat of the same problem is a new notification, not a replacement."""
        old = self._notification("k")
        old_unread = baker.make(
            "app.NotificationDelivery", notification=old, channel="inbox", recipient=self.alice
        )
        new = self._notification("k")

        InboxChannel().deliver(_notice(self.tenant, "k"), str(new.pk), [str(self.alice.pk)])

        self.assertTrue(NotificationDelivery.objects.filter(pk=old_unread.pk).exists())
        self.assertEqual(
            NotificationDelivery.objects.filter(
                recipient=self.alice, read_at__isnull=True, notification__dedupe_key="k"
            ).count(),
            2,
        )


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
