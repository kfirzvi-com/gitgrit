"""dispatch(): every channel on the route runs, outcomes are logged, re-runs never double-post."""
from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app.application.notifications import channels
from app.application.notifications.dispatcher import dispatch
from app.application.notifications.routing import Admins, Route
from app.domain.models import DeliveryLog, InboxItem


class _BrokenChannel:
    name = "broken"

    def deliver(self, notification, recipient_ids):
        raise RuntimeError("webhook said no")


def _route(*channel_names):
    return mock.patch(
        "app.application.notifications.dispatcher.route_for",
        return_value=Route((Admins(),), channel_names),
    )


class DispatchTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.admins = set()
        for role in ("owner", "admin"):
            user = baker.make("app.User")
            baker.make("app.Membership", user=user, tenant=self.tenant, role=role)
            self.admins.add(user.pk)
        baker.make("app.Membership", user=baker.make("app.User"), tenant=self.tenant, role="member")
        self.notification = baker.make(
            "app.Notification", tenant=self.tenant, kind="run.failed", severity="critical"
        )
        self.id = str(self.notification.pk)

    def _items(self):
        return InboxItem.objects.filter(notification=self.notification)

    def test_inbox_item_per_recipient_and_a_sent_log(self):
        with _route("inbox"):
            dispatch(self.id)

        self.assertEqual({i.recipient_id for i in self._items()}, self.admins)
        log = DeliveryLog.objects.get(notification=self.notification)
        self.assertEqual((log.channel, log.status), ("inbox", "sent"))

    def test_the_real_route_includes_the_triggerer(self):
        member = baker.make("app.User")
        baker.make("app.Membership", user=member, tenant=self.tenant, role="member")
        self.notification.context = {"triggered_by_user_ids": [str(member.pk)]}
        self.notification.save()

        dispatch(self.id)

        self.assertEqual({i.recipient_id for i in self._items()}, self.admins | {member.pk})

    def test_a_raising_channel_gets_a_failed_log_and_the_other_still_delivers(self):
        with mock.patch.dict(channels.CHANNELS, {"broken": _BrokenChannel()}), _route(
            "broken", "inbox"
        ), self.assertLogs("app.application.notifications.dispatcher", "ERROR"):
            dispatch(self.id)

        failed = DeliveryLog.objects.get(notification=self.notification, channel="broken")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "webhook said no")
        self.assertEqual(self._items().count(), 2)

    def test_running_twice_does_not_deliver_twice(self):
        with _route("inbox"):
            dispatch(self.id)
            dispatch(self.id)

        self.assertEqual(self._items().count(), 2)
        self.assertEqual(DeliveryLog.objects.filter(notification=self.notification).count(), 1)

    def test_a_deleted_notification_is_a_no_op(self):
        self.notification.delete()

        with self.assertLogs("app.application.notifications.dispatcher", "WARNING"):
            dispatch(self.id)

        self.assertFalse(InboxItem.objects.exists())
