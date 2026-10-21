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
        self.assertEqual(n.body, "GitHub or GitLab refused GitGrit's access token.")
        self.assertEqual(n.url, reverse("standard_execution_detail", args=[execution_id]))
        self.assertEqual(
            n.context,
            {
                "subject": "Acme",
                "project_id": str(self.project.pk),
                "project_name": "Acme",
                "execution_ids": [str(execution_id)],
                "trigger": "push",
                "triggered_by_user_ids": ["u1"],
            },
        )
        self.assertEqual(n.triggered_by_user_ids, ["u1"])

    def test_an_unknown_error_never_shows_raw(self):
        n = Notification.could_not_evaluate(
            project=self.project, error="FileNotFoundError: [Errno 2] No such file: '/policy.py'"
        )
        self.assertEqual(n.body, "The run stopped before it could score the project. Open it to see why.")

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
        self.assertEqual(n.body, "It took too long and was stopped.")
        self.assertEqual(n.url, reverse("tenant_settings") + "#section-llm")
        self.assertEqual(
            n.context,
            {"subject": "Acme", "project_id": str(self.project.pk), "project_name": "Acme"},
        )
        self.assertEqual(n.subject, "Acme")


class NewKindConstructorTests(TestCase):
    def setUp(self):
        self.project = baker.make("app.Project", name="Acme")
        self.actor = baker.make("app.User", first_name="Dana", last_name="Lee")

    def test_project_turned_critical(self):
        n = Notification.project_turned_critical(project=self.project, score_before=72.4, score_after=38.6)
        self.assertEqual((n.kind, n.severity), (Kind.PROJECT_CRITICAL, Severity.CRITICAL))
        self.assertEqual(n.title, "Score dropped to critical")
        self.assertEqual(n.body, "From C to D.")
        self.assertEqual(n.context["score"], 39)

    def test_runs_timed_out(self):
        n = Notification.runs_timed_out(project=self.project, execution_ids=["a", "b"])
        self.assertEqual((n.kind, n.severity), (Kind.RUN_TIMED_OUT, Severity.WARNING))
        self.assertEqual(n.title, "2 standard runs timed out")
        self.assertEqual(n.context["execution_ids"], ["a", "b"])

    def test_connection_broken_names_the_connection(self):
        connection = baker.make("app.PlatformConnection", display_name="GitHub Acme")
        n = Notification.connection_broken(project=self.project, connection=connection)
        self.assertEqual((n.kind, n.severity), (Kind.CONNECTION_BROKEN, Severity.CRITICAL))
        self.assertEqual(n.subject, "GitHub Acme")
        self.assertEqual(n.url, reverse("tenant_settings") + "#section-connections")
        self.assertIn("Acme", n.body)

    def test_ai_provider_failed(self):
        n = Notification.ai_provider_failed(project=self.project, error="credit balance is too low\n...")
        self.assertEqual((n.kind, n.severity), (Kind.AI_PROVIDER_FAILED, Severity.CRITICAL))
        self.assertEqual(n.subject, "AI provider")
        self.assertEqual(n.body, "The AI provider account is out of credit.")
        self.assertEqual(n.url, reverse("tenant_settings") + "#section-llm")

    def test_project_added_and_removed_name_the_actor(self):
        added = Notification.project_added(project=self.project, actor=self.actor)
        removed = Notification.project_removed(
            tenant_id=self.project.tenant_id, project_name="Acme", actor=self.actor
        )
        self.assertEqual((added.kind, added.severity), (Kind.PROJECT_ADDED, Severity.INFO))
        self.assertEqual(added.body, "Dana Lee added Acme.")
        self.assertEqual(added.actor_user_id, str(self.actor.pk))
        self.assertEqual((removed.kind, removed.subject), (Kind.PROJECT_REMOVED, "Acme"))
        self.assertEqual(removed.body, "Dana Lee removed Acme.")
        self.assertEqual(removed.url, reverse("project_list"))

    def test_member_joined(self):
        member = baker.make("app.User", first_name="Sam", last_name="Kim")
        n = Notification.member_joined(
            tenant_id=self.project.tenant_id, member=member, role="admin", actor=self.actor
        )
        self.assertEqual((n.kind, n.severity, n.subject), (Kind.MEMBER_JOINED, Severity.INFO, "Sam Kim"))
        self.assertEqual(n.body, "Dana Lee added Sam Kim as admin.")

    def test_member_removed_and_left(self):
        member = baker.make("app.User", first_name="Sam", last_name="Kim")
        removed = Notification.member_removed(tenant_id=self.project.tenant_id, member=member, actor=self.actor)
        left = Notification.member_removed(tenant_id=self.project.tenant_id, member=member, actor=member)
        self.assertEqual((removed.kind, removed.title), (Kind.MEMBER_REMOVED, "Member removed"))
        self.assertEqual(removed.body, "Dana Lee removed Sam Kim.")
        self.assertEqual((left.title, left.body), ("Member left", "Sam Kim left the workspace."))

    def test_member_role_changed(self):
        member = baker.make("app.User", first_name="Sam", last_name="Kim")
        n = Notification.member_role_changed(
            tenant_id=self.project.tenant_id, member=member, old_role="member", new_role="admin",
            actor=self.actor,
        )
        self.assertEqual((n.kind, n.title), (Kind.MEMBER_ROLE_CHANGED, "Role changed"))
        self.assertEqual(n.body, "Dana Lee made Sam Kim admin (was member).")
        self.assertEqual(n.member_user_id, str(member.pk))

    def test_standard_changed_and_activated(self):
        standard = baker.make("app.Standard", name="Pinned CI")
        changed = Notification.standard_changed(standard=standard, actor=self.actor)
        activated = Notification.standard_changed(standard=standard, actor=self.actor, activated=True)
        self.assertEqual((changed.kind, changed.title), (Kind.STANDARD_CHANGED, "Standard changed"))
        self.assertEqual(activated.title, "Standard activated")
        self.assertEqual(changed.subject, "Pinned CI")
        self.assertEqual(changed.url, reverse("standard_detail", args=[standard.pk]))

    def test_an_unknown_actor_reads_as_someone(self):
        n = Notification.project_added(project=self.project, actor=None)
        self.assertEqual(n.body, "Someone added Acme.")
        self.assertIsNone(n.actor_user_id)


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
