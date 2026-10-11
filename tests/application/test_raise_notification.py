"""raise_notification(): the row and its delivery job are written together, or not at all."""
from django.test import TestCase
from model_bakery import baker

from app.application.notifications.service import raise_notification
from app.domain.models import Notification
from tests.support import deliver_defer_patch


class RaiseNotificationTests(TestCase):
    def setUp(self):
        self.project = baker.make("app.Project", name="Acme")

    def _notification(self, **kwargs):
        return Notification.could_not_evaluate(project=self.project, error="boom", **kwargs)

    def test_stores_it_and_defers_one_delivery_with_its_id(self):
        with deliver_defer_patch() as defer:
            n = raise_notification(self._notification())

        stored = Notification.objects.get()
        self.assertEqual(stored.pk, n.pk)
        defer.assert_called_once_with(notification_id=str(n.pk))

    def test_a_failed_defer_leaves_no_row(self):
        with deliver_defer_patch(side_effect=RuntimeError("queue down")):
            with self.assertRaises(RuntimeError):
                raise_notification(self._notification())

        self.assertFalse(Notification.objects.exists())

    def test_a_notification_is_raised_once(self):
        with deliver_defer_patch():
            n = raise_notification(self._notification())
            with self.assertRaises(ValueError):
                raise_notification(n)

        self.assertEqual(Notification.objects.count(), 1)

    def test_a_long_title_is_cut_to_the_column_instead_of_failing(self):
        n = Notification._new(
            project=self.project, kind="run.failed", severity="critical", title="x" * 300,
            body="", url="", context={},
        )
        with deliver_defer_patch():
            raise_notification(n)

        self.assertEqual(len(Notification.objects.get().title), 255)
