"""The Notification aggregate: each named constructor holds its kind's wording,
severity and link; inbox items and delivery logs live and die with it."""
import uuid

from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.domain.models import DeliveryLog, InboxItem, Notification
from app.domain.notifications import Kind, Severity


class NamedConstructorTests(TestCase):
    def setUp(self):
        self.project = baker.make("app.Project", name="Acme")

    def test_could_not_evaluate(self):
        execution_id = uuid.uuid4()
        n = Notification.could_not_evaluate(
            project=self.project,
            error="401 Bad credentials\ntraceback...",
            execution_id=execution_id,
            execution_ids=[execution_id],
            trigger="push",
            triggered_by_user_ids=["u1"],
        )

        self.assertTrue(n._state.adding)  # built, not stored: raising stores it
        self.assertEqual(n.tenant_id, self.project.tenant_id)
        self.assertEqual(n.kind, Kind.RUN_FAILED)
        self.assertEqual(n.severity, Severity.CRITICAL)
        self.assertEqual(n.title, "GitGrit could not evaluate")
        self.assertEqual(n.body, "401 Bad credentials")
        self.assertEqual(n.url, reverse("standard_execution_detail", args=[execution_id]))
        self.assertEqual(
            n.context,
            {
                "project_id": str(self.project.pk),
                "project_name": "Acme",
                "execution_ids": [str(execution_id)],
                "trigger": "push",
                "triggered_by_user_ids": ["u1"],
            },
        )
        self.assertEqual(n.triggered_by_user_ids, ["u1"])

    def test_could_not_evaluate_without_a_run_links_to_the_project(self):
        n = Notification.could_not_evaluate(project=self.project, error="boom")

        self.assertEqual(n.url, reverse("project_detail", args=[self.project.pk]))
        self.assertNotIn("trigger", n.context)
        self.assertNotIn("triggered_by_user_ids", n.context)
        self.assertEqual(n.triggered_by_user_ids, [])

    def test_standards_failing(self):
        n = Notification.standards_failing(
            project=self.project,
            failed_names=["README present", "Pinned CI"],
            failed_standard_ids=["s1", "s2"],
            execution_ids=["e1"],
            score=66.6,
            trigger="manual",
        )

        self.assertEqual(n.kind, Kind.STANDARDS_FAILING)
        self.assertEqual(n.severity, Severity.WARNING)
        self.assertEqual(n.title, "2 standards failed")
        self.assertEqual(n.body, "README present, Pinned CI")
        self.assertEqual(n.url, reverse("project_detail", args=[self.project.pk]) + "#compliance")
        self.assertEqual(n.context["score"], 67)
        self.assertEqual(n.context["failed_standard_ids"], ["s1", "s2"])
        self.assertEqual(n.context["trigger"], "manual")

    def test_standards_failing_singular_title(self):
        n = Notification.standards_failing(
            project=self.project, failed_names=["Pinned CI"], failed_standard_ids=["s1"]
        )
        self.assertEqual(n.title, "1 standard failed")
        self.assertNotIn("score", n.context)

    def test_standards_failing_names_at_most_three(self):
        n = Notification.standards_failing(
            project=self.project,
            failed_names=[f"Std {i}" for i in range(5)],
            failed_standard_ids=[f"s{i}" for i in range(5)],
        )
        self.assertEqual(n.title, "5 standards failed")
        self.assertEqual(n.body, "Std 0, Std 1, Std 2 and 2 more")

    def test_graph_failed(self):
        n = Notification.graph_failed(project=self.project, error="LLM timed out\ntraceback...")

        self.assertEqual(n.kind, Kind.GRAPH_FAILED)
        self.assertEqual(n.severity, Severity.WARNING)
        self.assertEqual(n.title, "Dependency graph failed")
        self.assertEqual(n.body, "LLM timed out")
        self.assertEqual(n.url, reverse("tenant_settings") + "#section-llm")
        self.assertEqual(n.context, {"project_id": str(self.project.pk), "project_name": "Acme"})


class LifecycleTests(TestCase):
    def test_inbox_items_and_delivery_logs_go_with_their_notification(self):
        notification = baker.make("app.Notification", kind=Kind.RUN_FAILED, severity="critical")
        baker.make("app.InboxItem", notification=notification, _quantity=2)
        baker.make("app.DeliveryLog", notification=notification, channel="inbox", status="sent")

        notification.delete()

        self.assertFalse(InboxItem.objects.exists())
        self.assertFalse(DeliveryLog.objects.exists())

    def test_a_new_inbox_item_is_unread(self):
        item = baker.make("app.InboxItem")
        self.assertTrue(item.is_unread)
