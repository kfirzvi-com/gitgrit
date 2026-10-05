"""A Notification is the fact; each delivery is one recipient's copy on one
channel, so the fact and its copies must live and die together."""
from django.test import TestCase
from model_bakery import baker

from app.domain.models import Notification, NotificationDelivery


class NotificationModelTests(TestCase):
    def setUp(self):
        self.notification = baker.make(
            "app.Notification", kind="run.failed", severity="critical"
        )

    def test_a_notification_holds_its_deliveries(self):
        baker.make(
            "app.NotificationDelivery",
            notification=self.notification,
            channel="inbox",
            recipient=baker.make("app.User"),
            _quantity=2,
        )

        self.assertEqual(self.notification.deliveries.count(), 2)

    def test_a_delivery_may_have_no_recipient(self):
        """Channels like log have no person on the other end."""
        delivery = baker.make(
            "app.NotificationDelivery",
            notification=self.notification,
            channel="log",
            recipient=None,
        )

        delivery.refresh_from_db()
        self.assertIsNone(delivery.recipient)

    def test_deleting_the_notification_deletes_its_deliveries(self):
        baker.make(
            "app.NotificationDelivery",
            notification=self.notification,
            channel="inbox",
            _quantity=2,
        )

        self.notification.delete()

        self.assertFalse(Notification.objects.exists())
        self.assertFalse(NotificationDelivery.objects.exists())

    def test_a_new_delivery_is_pending(self):
        delivery = NotificationDelivery.objects.create(
            notification=self.notification, channel="inbox"
        )

        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)
