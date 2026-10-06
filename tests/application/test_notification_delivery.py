"""deliver(): every channel in the rule runs, failures are recorded, re-runs never double-post."""

from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app.application.notifications import channels
from app.application.notifications.delivery import deliver, notice_from_row
from app.domain.models import NotificationDelivery
from app.domain.notifications import Audience, Rule, Severity


class _BrokenChannel:
    name = "broken"

    def deliver(self, notice, notification_id, recipient_ids):
        raise RuntimeError("webhook said no")


def _rule(*channel_names):
    return mock.patch(
        "app.application.notifications.delivery.rule_for",
        return_value=Rule(Audience.admins(), channel_names),
    )


class DeliverTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.admins = set()
        for role in ("owner", "admin"):
            user = baker.make("app.User")
            baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
            self.admins.add(user.pk)
        baker.make("app.Membership", user=baker.make("app.User"), tenant=self.tenant, role="member")
        self.notification = baker.make(
            "app.Notification",
            tenant=self.tenant,
            kind="run.failed",
            severity="critical",
            title="Run failed",
            context={"project_id": "p1", "mentioned_user_ids": []},
        )
        self.id = str(self.notification.pk)

    def _inbox_rows(self):
        return NotificationDelivery.objects.filter(
            notification=self.notification, channel="inbox"
        )

    def test_notice_from_row_moves_mentions_out_of_context(self):
        self.notification.context = {"project_id": "p1", "mentioned_user_ids": ["u1"]}

        notice = notice_from_row(self.notification)

        self.assertEqual(notice.context, {"project_id": "p1"})
        self.assertEqual(notice.mentioned_user_ids, ("u1",))
        self.assertEqual(notice.severity, Severity.CRITICAL)
        self.assertIsNone(notice.dedupe_key)

    def test_inbox_row_per_admin_and_log_channel_logs(self):
        with _rule("inbox", "log"), self.assertLogs(
            "app.application.notifications.channels", "INFO"
        ) as logs:
            deliver(self.id)

        rows = self._inbox_rows()
        self.assertEqual({r.recipient_id for r in rows}, self.admins)
        self.assertTrue(all(r.status == "sent" for r in rows))
        self.assertIn("kind=run.failed", logs.output[0])

    def test_a_raising_channel_gets_a_failed_row_and_the_other_still_delivers(self):
        with mock.patch.dict(channels.CHANNELS, {"broken": _BrokenChannel()}), _rule(
            "broken", "inbox"
        ), self.assertLogs("app.application.notifications.delivery", "ERROR"):
            deliver(self.id)

        failed = NotificationDelivery.objects.get(
            notification=self.notification, channel="broken"
        )
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "webhook said no")
        self.assertIsNone(failed.recipient_id)
        self.assertEqual(self._inbox_rows().count(), 2)

    def test_running_twice_does_not_add_inbox_rows(self):
        with _rule("inbox"):
            deliver(self.id)
            deliver(self.id)

        self.assertEqual(self._inbox_rows().count(), 2)

    def test_a_deleted_notification_is_a_no_op(self):
        self.notification.delete()

        with self.assertLogs("app.application.notifications.delivery", "WARNING"):
            deliver(self.id)

        self.assertFalse(NotificationDelivery.objects.exists())
