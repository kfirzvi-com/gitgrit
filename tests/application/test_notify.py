"""notify(): the row and its delivery job are written together, or not at all."""

from django.test import TestCase
from model_bakery import baker

from app.application.notifications import notify
from app.domain.models import Notification
from app.domain.notifications import Notice, Severity
from tests.support import notify_defer_patch


class NotifyTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.notice = Notice(
            kind="run.failed",
            tenant_id=str(self.tenant.pk),
            severity=Severity.CRITICAL,
            title="Run failed",
            body="The sandbox exited",
            url="/projects/1",
            context={"project_id": "p1"},
            dedupe_key="run:p1",
            mentioned_user_ids=("u1",),
        )

    def test_writes_the_row_and_defers_once_with_its_id(self):
        with notify_defer_patch() as defer:
            notification_id = notify(self.notice)

        row = Notification.objects.get()
        self.assertEqual(notification_id, str(row.pk))
        defer.assert_called_once_with(notification_id=str(row.pk))
        self.assertEqual(row.tenant_id, self.tenant.pk)
        self.assertEqual(row.kind, "run.failed")
        self.assertEqual(row.severity, "critical")
        self.assertEqual(row.dedupe_key, "run:p1")
        self.assertEqual(
            row.context, {"project_id": "p1", "mentioned_user_ids": ["u1"]}
        )

    def test_a_failed_defer_leaves_no_row(self):
        with notify_defer_patch(side_effect=RuntimeError("queue down")):
            with self.assertRaises(RuntimeError):
                notify(self.notice)

        self.assertFalse(Notification.objects.exists())
