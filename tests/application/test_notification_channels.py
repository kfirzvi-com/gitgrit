"""Channels: the inbox gives each recipient their own new item."""
from django.test import SimpleTestCase, TestCase
from model_bakery import baker

from app.application.notifications.channels import InboxChannel, channel_for
from app.domain.models import InboxItem


class InboxChannelTests(TestCase):
    def setUp(self):
        self.notification = baker.make("app.Notification", kind="run.failed", severity="critical")
        self.alice = baker.make("app.User")
        self.bob = baker.make("app.User")

    def test_one_unread_item_per_recipient(self):
        InboxChannel().deliver(self.notification, [str(self.alice.pk), str(self.bob.pk)])

        items = InboxItem.objects.filter(notification=self.notification)
        self.assertEqual({i.recipient_id for i in items}, {self.alice.pk, self.bob.pk})
        self.assertTrue(all(i.is_unread for i in items))

    def test_a_repeat_is_a_new_item_and_the_old_one_stays(self):
        """Each notification is its own item; nothing is merged or replaced."""
        older = baker.make("app.Notification", tenant=self.notification.tenant, kind="run.failed")
        old_item = baker.make("app.InboxItem", notification=older, recipient=self.alice)

        InboxChannel().deliver(self.notification, [str(self.alice.pk)])

        self.assertTrue(InboxItem.objects.filter(pk=old_item.pk).exists())
        self.assertEqual(InboxItem.objects.filter(recipient=self.alice, read_at__isnull=True).count(), 2)


class ChannelForTests(SimpleTestCase):
    def test_known_names_resolve(self):
        self.assertEqual(channel_for("inbox").name, "inbox")

    def test_unknown_name_raises_key_error(self):
        with self.assertRaises(KeyError):
            channel_for("x")
