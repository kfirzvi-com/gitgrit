"""Notification policies: a finished run or a broken map becomes the right notification."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import event_bus, subscribers
from app.application.notifications.notification_policies import (
    AIProviderFailedNotificationPolicy,
    CouldNotEvaluateNotificationPolicy,
    GraphBrokeNotificationPolicy,
    MemberJoinedNotificationPolicy,
    MemberRemovedNotificationPolicy,
    MemberRoleChangedNotificationPolicy,
    ProjectAddedNotificationPolicy,
    ProjectRemovedNotificationPolicy,
    ProjectTurnedCriticalNotificationPolicy,
    RunsTimedOutNotificationPolicy,
    StandardChangedNotificationPolicy,
    StandardsFailingNotificationPolicy,
)
from app.domain.events import (
    DependencyInferenceFailed,
    MemberJoined,
    MemberRemoved,
    MemberRoleChanged,
    ProjectCreated,
    ProjectDeleted,
    StandardActivated,
    StandardRunFinished,
    StandardRunsTimedOut,
    StandardSaved,
)
from app.domain.models import Notification, StandardExecution
from tests.support import deliver_defer_patch, score_commit


class _PolicyTestCase(TestCase):
    def setUp(self):
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        patch = deliver_defer_patch()
        self.defer = patch.start()
        self.addCleanup(patch.stop)
        # The Git connection probe is a network call; each test says how it answers.
        probe = mock.patch(
            "app.application.notifications.notification_policies._connection_works",
            return_value=True,
        )
        self.connection_works = probe.start()
        self.addCleanup(probe.stop)
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, name="Acme")

    def _row(self, status, score=0, name=None, attach=True, **kwargs):
        standard = baker.make("app.Standard", tenant=self.tenant)
        if attach:
            self.project.standards.add(standard)
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=name or standard.name,
            status=status,
            score=score,
            **{"event_type": "manual", **kwargs},
        )

    def _scored(self, rows, sha="a" * 40):
        """Put ``rows`` on one checked commit of the default branch and score it."""
        check = baker.make(
            "app.CommitCheck", project=self.project, branch=self.project.default_branch, commit_sha=sha
        )
        StandardExecution.objects.filter(pk__in=[r.pk for r in rows]).update(commit_check=check)
        return score_commit(self.project, sha)

    def _event(self, rows, passed=0, failed=0, errored=0, error=""):
        return StandardRunFinished(
            project_id=str(self.project.pk),
            tenant_id=str(self.tenant.pk),
            execution_ids=tuple(str(r.pk) for r in rows),
            passed=passed,
            failed=failed,
            errored=errored,
            error=error,
        )


class CouldNotEvaluateNotificationPolicyTests(_PolicyTestCase):
    policy = CouldNotEvaluateNotificationPolicy()

    def _errored(self, **kwargs):
        return self._row(StandardExecution.Status.ERROR, **kwargs)

    def test_job_level_error_raises_it_and_queues_delivery(self):
        row = self._errored()
        self.policy.handle(self._event([row], errored=1, error="401 Bad credentials\ntraceback..."))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "run.failed")
        self.assertEqual(n.body, "GitHub or GitLab refused GitGrit's access token.")
        self.assertEqual(n.url, reverse("standard_execution_detail", args=[row.pk]))
        self.assertEqual(n.context["project_name"], "Acme")
        self.assertEqual(n.context["execution_ids"], [str(row.pk)])
        self.assertEqual(n.context["trigger"], "manual")
        self.defer.assert_called_once_with(notification_id=str(n.pk))

    def test_a_refused_token_with_a_dead_connection_says_the_connection_is_broken(self):
        self.connection_works.return_value = False
        row = self._errored()
        self.policy.handle(self._event([row], errored=1, error="401 Bad credentials"))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "connection.broken")
        self.assertEqual(n.subject, self.project.platform_connection.display_name)

    def test_a_refused_token_with_a_working_connection_is_still_could_not_evaluate(self):
        row = self._errored()
        self.policy.handle(self._event([row], errored=1, error="401 Bad credentials"))
        self.assertEqual(Notification.objects.get().kind, "run.failed")

    def test_other_errors_never_probe_the_connection(self):
        row = self._errored()
        self.policy.handle(self._event([row], errored=1, error="sandbox exploded"))
        self.connection_works.assert_not_called()

    def test_all_rows_errored_explains_the_row_error(self):
        row = self._errored(details={"error": "Timed out after 30s"})
        self.policy.handle(self._event([row], errored=1))
        self.assertEqual(Notification.objects.get().body, "It took too long and was stopped.")

    def test_sandbox_error_flag_falls_back_to_the_message(self):
        """The sandbox marks a raising standard with ``details={"error": True}``
        and puts the traceback in ``message``; the reason comes from there."""
        row = self._errored(
            details={"error": True},
            message=(
                "Standard execution error: Traceback (most recent call last):\n"
                '  File "/entrypoint.py", line 1, in <module>\n'
                "TimeoutError: timed out reading the repository"
            ),
        )
        self.policy.handle(self._event([row], errored=1))
        self.assertEqual(Notification.objects.get().body, "It took too long and was stopped.")

    def test_a_mixed_run_is_not_its_business(self):
        rows = [self._errored(), self._row(StandardExecution.Status.PASSED, 100)]
        self.policy.handle(self._event(rows, passed=1, failed=1, errored=1))
        self.assertFalse(Notification.objects.exists())

    def test_the_triggering_user_is_recorded_for_routing(self):
        user = baker.make("app.User")
        row = self._errored(triggered_by_user=user)
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertEqual(Notification.objects.get().triggered_by_user_ids, [str(user.pk)])

    def test_trigger_prefers_the_webhook_event_over_the_actor(self):
        row = self._errored(event_type="push", triggered_by="octocat")
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertEqual(Notification.objects.get().context["trigger"], "push")

    def test_trigger_uses_the_app_reason_for_manual_runs(self):
        row = self._errored(event_type="manual", triggered_by="attached")
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertEqual(Notification.objects.get().context["trigger"], "attached")

    def test_trigger_falls_back_to_the_event_type(self):
        row = self._errored(event_type="schedule", triggered_by="someone")
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertEqual(Notification.objects.get().context["trigger"], "schedule")

    def test_trigger_is_omitted_when_unknown(self):
        row = self._errored(event_type="", triggered_by="")
        self.policy.handle(self._event([row], errored=1, error="boom"))
        self.assertNotIn("trigger", Notification.objects.get().context)

    def test_the_same_event_twice_raises_two(self):
        event = self._event([self._errored()], errored=1, error="boom")
        self.policy.handle(event)
        self.policy.handle(event)
        self.assertEqual(Notification.objects.count(), 2)

    def test_another_workspaces_project_is_ignored(self):
        event = StandardRunFinished(
            project_id=str(self.project.pk), tenant_id=str(baker.make("app.Tenant").pk),
            execution_ids=(), passed=0, failed=0, errored=1, error="boom",
        )
        self.policy.handle(event)
        self.assertFalse(Notification.objects.exists())


class StandardsFailingNotificationPolicyTests(_PolicyTestCase):
    policy = StandardsFailingNotificationPolicy()

    def _failed(self, score, name=None, **kwargs):
        return self._row(StandardExecution.Status.FAILED, score, name, **kwargs)

    def test_a_failing_run_raises_one_for_the_run(self):
        rows = [
            self._failed(80, "Pinned CI"),
            self._failed(20, "README present"),
            self._row(StandardExecution.Status.PASSED, 100),
        ]
        self._scored(rows)
        self.policy.handle(self._event(rows, passed=1, failed=2))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "standards.failing")
        self.assertEqual(n.title, "2 standards failed")
        self.assertEqual(n.body, "README present, Pinned CI")  # worst first
        self.assertEqual(n.context["score"], 67)
        self.assertEqual(len(n.context["failed_standard_ids"]), 2)
        self.assertEqual(n.context["trigger"], "manual")

    def test_the_count_is_this_runs_failures_not_the_projects(self):
        older = self._failed(0, "Older failure")
        rows = [self._failed(40, "Pinned CI")]
        self._scored([older, *rows])
        self.policy.handle(self._event(rows, failed=1))

        n = Notification.objects.get()
        self.assertEqual(n.title, "1 standard failed")
        self.assertEqual(n.body, "Pinned CI")
        self.assertEqual(n.context["score"], 20)

    def test_trigger_comes_from_this_runs_rows(self):
        rows = [self._failed(10, event_type="pull_request", triggered_by="octocat")]
        self.policy.handle(self._event(rows, failed=1))
        self.assertEqual(Notification.objects.get().context["trigger"], "pull_request")

    def test_a_clean_run_raises_nothing(self):
        rows = [self._row(StandardExecution.Status.PASSED, 100)]
        self.policy.handle(self._event(rows, passed=1))
        self.assertFalse(Notification.objects.exists())

    def test_a_run_that_could_not_be_evaluated_is_left_to_the_other_policy(self):
        rows = [self._failed(10)]
        self.policy.handle(self._event(rows, failed=1, error="boom"))
        self.assertFalse(Notification.objects.exists())

    def test_a_detached_standard_still_counts_when_it_failed_in_this_run(self):
        rows = [self._failed(0, "README present", attach=False)]
        self.policy.handle(self._event(rows, failed=1))
        self.assertEqual(Notification.objects.get().title, "1 standard failed")

    def test_a_run_with_no_failed_rows_raises_nothing(self):
        rows = [self._row(StandardExecution.Status.PASSED, 100)]
        self.policy.handle(self._event(rows, passed=1, failed=1))
        self.assertFalse(Notification.objects.exists())

    def test_the_triggering_user_is_recorded_for_routing(self):
        user = baker.make("app.User")
        rows = [self._failed(10, triggered_by_user=user)]
        self.policy.handle(self._event(rows, failed=1))
        self.assertEqual(Notification.objects.get().triggered_by_user_ids, [str(user.pk)])


class ProjectTurnedCriticalNotificationPolicyTests(_PolicyTestCase):
    policy = ProjectTurnedCriticalNotificationPolicy()

    def _attached_result(self, standard, score, status):
        return baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=standard.name, status=status, score=score, event_type="manual",
        )

    def test_a_run_that_drops_the_score_into_critical_raises_it(self):
        standard = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(standard)
        self._scored([self._attached_result(standard, 90, StandardExecution.Status.PASSED)], sha="a" * 40)
        new = self._attached_result(standard, 20, StandardExecution.Status.FAILED)
        self._scored([new], sha="b" * 40)

        self.policy.handle(self._event([new], failed=1))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "project.critical")
        self.assertEqual(n.body, "From A to D.")

    def test_a_project_that_was_already_critical_raises_nothing(self):
        standard = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(standard)
        self._scored([self._attached_result(standard, 30, StandardExecution.Status.FAILED)], sha="a" * 40)
        new = self._attached_result(standard, 10, StandardExecution.Status.FAILED)
        self._scored([new], sha="b" * 40)

        self.policy.handle(self._event([new], failed=1))

        self.assertFalse(Notification.objects.exists())

    def test_a_first_run_has_nothing_to_drop_from(self):
        new = self._row(StandardExecution.Status.FAILED, 10)
        self.policy.handle(self._event([new], failed=1))
        self.assertFalse(Notification.objects.exists())


class RunsTimedOutNotificationPolicyTests(_PolicyTestCase):
    policy = RunsTimedOutNotificationPolicy()

    def test_expired_runs_raise_one_for_their_project(self):
        user = baker.make("app.User")
        rows = [self._row(StandardExecution.Status.ERROR, triggered_by_user=user) for _ in range(2)]

        self.policy.handle(
            StandardRunsTimedOut(
                project_id=str(self.project.pk), tenant_id=str(self.tenant.pk),
                execution_ids=tuple(str(r.pk) for r in rows),
            )
        )

        n = Notification.objects.get()
        self.assertEqual((n.kind, n.title), ("run.timed_out", "2 standard runs timed out"))
        self.assertEqual(n.triggered_by_user_ids, [str(user.pk)])


class GraphBrokeNotificationPolicyTests(_PolicyTestCase):
    policy = GraphBrokeNotificationPolicy()

    def _event(self, had_worked_before=True, tenant_id=None):
        return DependencyInferenceFailed(
            project_id=str(self.project.pk),
            tenant_id=tenant_id or str(self.tenant.pk),
            error="LLM timed out\ntraceback...",
            had_worked_before=had_worked_before,
        )

    def test_a_map_that_used_to_build_raises_it(self):
        self.policy.handle(self._event())
        n = Notification.objects.get()
        self.assertEqual(n.kind, "graph.failed")
        self.assertEqual(n.body, "It took too long and was stopped.")

    def test_a_map_that_never_built_is_quiet(self):
        self.policy.handle(self._event(had_worked_before=False))
        self.assertFalse(Notification.objects.exists())

    def test_another_workspace_is_quiet(self):
        self.policy.handle(self._event(tenant_id=str(baker.make("app.Tenant").pk)))
        self.assertFalse(Notification.objects.exists())

    def test_an_ai_provider_refusal_is_left_to_the_provider_policy(self):
        event = DependencyInferenceFailed(
            project_id=str(self.project.pk), tenant_id=str(self.tenant.pk),
            error="credit balance is too low", had_worked_before=True, provider_status=400,
        )
        self.policy.handle(event)
        self.assertFalse(Notification.objects.exists())


class AIProviderFailedNotificationPolicyTests(_PolicyTestCase):
    policy = AIProviderFailedNotificationPolicy()

    def _event(self, error="x", status=None, had_worked_before=False):
        return DependencyInferenceFailed(
            project_id=str(self.project.pk), tenant_id=str(self.tenant.pk), error=error,
            had_worked_before=had_worked_before, provider_status=status,
        )

    def test_a_refusal_raises_it_even_for_a_map_that_never_built(self):
        self.policy.handle(self._event(error="invalid x-api-key", status=401))
        n = Notification.objects.get()
        self.assertEqual((n.kind, n.severity), ("ai_provider.failed", "critical"))

    def test_other_map_failures_are_not_its_business(self):
        self.policy.handle(self._event(error="timed out", status=500, had_worked_before=True))
        self.assertFalse(Notification.objects.exists())


class WorkspaceChangeNotificationPolicyTests(_PolicyTestCase):
    def setUp(self):
        super().setUp()
        self.actor = baker.make("app.User", first_name="Dana", last_name="Lee")

    def test_project_added(self):
        ProjectAddedNotificationPolicy().handle(
            ProjectCreated(project_id=str(self.project.pk), tenant_id=str(self.tenant.pk), user_id=str(self.actor.pk))
        )
        n = Notification.objects.get()
        self.assertEqual((n.kind, n.body), ("project.added", "Dana Lee added Acme."))
        self.assertEqual(n.actor_user_id, str(self.actor.pk))

    def test_project_removed_after_the_row_is_gone(self):
        ProjectRemovedNotificationPolicy().handle(
            ProjectDeleted(
                project_id="gone", tenant_id=str(self.tenant.pk), project_name="Old repo",
                user_id=str(self.actor.pk),
            )
        )
        n = Notification.objects.get()
        self.assertEqual((n.kind, n.subject, n.tenant_id), ("project.removed", "Old repo", self.tenant.pk))

    def test_member_joined(self):
        member = baker.make("app.User", first_name="Sam", last_name="Kim")
        MemberJoinedNotificationPolicy().handle(
            MemberJoined(
                tenant_id=str(self.tenant.pk), user_id=str(member.pk), role="member",
                added_by_user_id=str(self.actor.pk),
            )
        )
        self.assertEqual(Notification.objects.get().body, "Dana Lee added Sam Kim as member.")

    def test_member_removed(self):
        member = baker.make("app.User", first_name="Sam", last_name="Kim")
        MemberRemovedNotificationPolicy().handle(
            MemberRemoved(tenant_id=str(self.tenant.pk), user_id=str(member.pk), removed_by_user_id=str(self.actor.pk))
        )
        self.assertEqual(Notification.objects.get().body, "Dana Lee removed Sam Kim.")

    def test_member_role_changed(self):
        member = baker.make("app.User", first_name="Sam", last_name="Kim")
        MemberRoleChangedNotificationPolicy().handle(
            MemberRoleChanged(
                tenant_id=str(self.tenant.pk), user_id=str(member.pk), old_role="member",
                new_role="admin", changed_by_user_id=str(self.actor.pk),
            )
        )
        self.assertEqual(Notification.objects.get().body, "Dana Lee made Sam Kim admin (was member).")

    def test_standard_saved_and_activated(self):
        standard = baker.make("app.Standard", tenant=self.tenant, name="Pinned CI")
        policy = StandardChangedNotificationPolicy()
        policy.handle(StandardSaved(standard_id=str(standard.pk), tenant_id=str(self.tenant.pk), user_id=str(self.actor.pk)))
        policy.handle(StandardActivated(standard_id=str(standard.pk), tenant_id=str(self.tenant.pk), user_id=str(self.actor.pk)))
        self.assertEqual(
            sorted(Notification.objects.values_list("title", flat=True)),
            ["Standard activated", "Standard changed"],
        )

    def test_another_workspaces_standard_is_ignored(self):
        standard = baker.make("app.Standard", tenant=baker.make("app.Tenant"))
        StandardChangedNotificationPolicy().handle(
            StandardSaved(standard_id=str(standard.pk), tenant_id=str(self.tenant.pk))
        )
        self.assertFalse(Notification.objects.exists())


class RegistrationTests(_PolicyTestCase):
    def test_published_events_reach_the_notification_policies(self):
        event_bus.clear()
        subscribers.register()
        row = self._row(StandardExecution.Status.ERROR)

        event_bus.publish(self._event([row], errored=1, error="boom"))
        event_bus.publish(
            DependencyInferenceFailed(
                project_id=str(self.project.pk), tenant_id=str(self.tenant.pk),
                error="x", had_worked_before=True,
            )
        )

        self.assertEqual(
            sorted(Notification.objects.values_list("kind", flat=True)),
            ["graph.failed", "run.failed"],
        )
