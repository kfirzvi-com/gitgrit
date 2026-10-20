"""Notification policies: a finished run or a broken map becomes the right notification."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from app.application import event_bus, grading_service, subscribers
from app.application.notifications.notification_policies import (
    AIProviderFailedNotificationPolicy,
    CouldNotEvaluateNotificationPolicy,
    GradeUnverifiedNotificationPolicy,
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
from app.domain.models import Notification, ProjectStandard, StandardExecution
from app.domain.notifications.notification_routing import route_for
from tests.support import deliver_defer_patch


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
        self.policy.handle(self._event(rows, passed=1, failed=2))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "standards.failing")
        self.assertEqual(n.title, "2 standards failed")
        # Worst first; one of three passed is a D.
        self.assertEqual(n.body, "Grade D — 2 standards failing: README present, Pinned CI")
        self.assertEqual(n.context["grade"], "D")
        self.assertEqual(len(n.context["failed_standard_ids"]), 2)
        self.assertEqual(n.context["trigger"], "manual")

    def test_failing_body_says_letter_and_reason_not_a_score(self):
        for _ in range(3):
            self._row(StandardExecution.Status.PASSED, 100)
        rows = [self._failed(10, "Pinned CI")]
        self.policy.handle(self._event(rows, failed=1))

        n = Notification.objects.get()
        self.assertEqual(n.body, "Grade B — 1 standard failing: Pinned CI")
        self.assertNotIn("/100", n.body)
        self.assertNotIn("%", n.body)
        self.assertNotIn("score", n.context)

    def test_the_count_is_this_runs_failures_but_the_grade_is_the_projects(self):
        self._failed(0, "Older failure")
        rows = [self._failed(40, "Pinned CI")]
        self.policy.handle(self._event(rows, failed=1))

        n = Notification.objects.get()
        self.assertEqual(n.title, "1 standard failed")
        self.assertEqual(n.body, "Grade D — 2 standards failing: Pinned CI")

    def test_a_failure_on_another_branch_names_no_grade(self):
        """The grade reads the home branch, so a feature-branch failure
        leaves it where it was; saying "Grade A+ — perfect" under "1
        standard failed" would be nonsense."""
        self._row(StandardExecution.Status.PASSED, 100)
        rows = [self._failed(10, "Pinned CI", event_type="push", ref="refs/heads/feature")]
        self.policy.handle(self._event(rows, failed=1))

        n = Notification.objects.get()
        self.assertEqual(n.body, "Pinned CI")
        self.assertNotIn("grade", n.context)

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
    """"Grade dropped to F": a critical standard started failing on its home
    branch. The policy compares the grade without this run's rows to the
    grade with them."""

    policy = ProjectTurnedCriticalNotificationPolicy()

    def _standard(self, name, critical):
        standard = baker.make("app.Standard", tenant=self.tenant, name=name)
        ProjectStandard.objects.create(project=self.project, standard=standard, level="critical" if critical else "high")
        return standard

    def _result(self, standard, status, **kwargs):
        return baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=standard.name, status=status, **{"event_type": "manual", **kwargs},
        )

    def test_turned_f_raised_when_a_critical_starts_failing(self):
        critical = self._standard("No secrets", critical=True)
        self._result(critical, StandardExecution.Status.PASSED)
        new = self._result(critical, StandardExecution.Status.FAILED)

        self.policy.handle(self._event([new], failed=1))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "project.critical")
        self.assertEqual(n.title, "Grade dropped to F")
        self.assertEqual(n.body, "No secrets failing")
        self.assertEqual((n.context["grade"], n.context["grade_before"]), ("F", "A+"))
        self.assertNotIn("score", n.context)

    def test_turned_f_not_raised_for_could_not_verify(self):
        """That F is the could-not-verify alert's fact; one notice per fact."""
        critical = self._standard("No secrets", critical=True)
        self._result(critical, StandardExecution.Status.PASSED)
        new = self._result(critical, StandardExecution.Status.ERROR)
        other = self._result(self._standard("Pinned CI", critical=False), StandardExecution.Status.PASSED)

        self.policy.handle(self._event([new, other], passed=1, errored=1))

        self.assertFalse(Notification.objects.exists())

    def test_turned_f_not_raised_when_already_f(self):
        critical = self._standard("No secrets", critical=True)
        self._result(critical, StandardExecution.Status.FAILED)
        new = self._result(critical, StandardExecution.Status.FAILED)

        self.policy.handle(self._event([new], failed=1))

        self.assertFalse(Notification.objects.exists())

    def test_a_non_critical_failure_never_reaches_f(self):
        standard = self._standard("Pinned CI", critical=False)
        self._result(standard, StandardExecution.Status.PASSED)
        new = self._result(standard, StandardExecution.Status.FAILED)

        self.policy.handle(self._event([new], failed=1))

        self.assertFalse(Notification.objects.exists())

    def test_a_first_run_has_nothing_to_drop_from(self):
        critical = self._standard("No secrets", critical=True)
        new = self._result(critical, StandardExecution.Status.FAILED)
        self.policy.handle(self._event([new], failed=1))
        self.assertFalse(Notification.objects.exists())

    def test_a_critical_failure_on_another_branch_is_not_a_drop(self):
        critical = self._standard("No secrets", critical=True)
        self._result(critical, StandardExecution.Status.PASSED)
        new = self._result(
            critical, StandardExecution.Status.FAILED, event_type="push", ref="refs/heads/feature"
        )
        self.policy.handle(self._event([new], failed=1))
        self.assertFalse(Notification.objects.exists())


class OnePicturePerRunTests(_PolicyTestCase):
    """A finished run reads the grade before and after it once each, however
    many policies look at them."""

    def test_every_policy_of_one_event_shares_the_two_pictures(self):
        Status = StandardExecution.Status
        failing = baker.make("app.Standard", tenant=self.tenant, name="No secrets")
        unverified = baker.make("app.Standard", tenant=self.tenant, name="Licences")
        rows = []
        for standard in (failing, unverified):
            ProjectStandard.objects.create(project=self.project, standard=standard, level="critical")
            baker.make(
                "app.StandardExecution", project=self.project, standard=standard,
                standard_name=standard.name, status=Status.PASSED, event_type="manual",
            )
        for standard, status in ((failing, Status.FAILED), (unverified, Status.ERROR)):
            rows.append(baker.make(
                "app.StandardExecution", project=self.project, standard=standard,
                standard_name=standard.name, status=status, event_type="manual",
            ))
        event = self._event(rows, failed=1, errored=1)

        with mock.patch.object(
            grading_service, "grade_for_project", wraps=grading_service.grade_for_project
        ) as grade_for_project, mock.patch(
            "app.application.grading_service.current_results", wraps=grading_service.current_results
        ) as current_results:
            StandardsFailingNotificationPolicy().handle(event)
            ProjectTurnedCriticalNotificationPolicy().handle(event)
            GradeUnverifiedNotificationPolicy().handle(event)

        ids = tuple(str(r.pk) for r in rows)
        excluded = [c for c in grade_for_project.call_args_list if c.kwargs.get("exclude_execution_ids")]
        self.assertEqual(grade_for_project.call_count, 2)
        self.assertEqual(len(excluded), 1)
        self.assertEqual(tuple(str(i) for i in excluded[0].kwargs["exclude_execution_ids"]), ids)
        self.assertEqual(current_results.call_count, 2)
        kinds = sorted(Notification.objects.values_list("kind", flat=True))
        self.assertEqual(len(kinds), 3, kinds)


class GradeUnverifiedNotificationPolicyTests(_PolicyTestCase):
    """The could-not-verify alert goes out on the transition only: a run on
    the standard's home branch leaves a critical attachment errored in its
    own code when it was not errored before. The transition rule is the
    dedupe; the inbox has none."""

    policy = GradeUnverifiedNotificationPolicy()

    def setUp(self):
        super().setUp()
        self.standard = self._standard("No secrets", critical=True)

    def _standard(self, name, critical):
        standard = baker.make("app.Standard", tenant=self.tenant, name=name)
        ProjectStandard.objects.create(project=self.project, standard=standard, level="critical" if critical else "high")
        return standard

    def _result(
        self,
        status,
        standard=None,
        event_type="push",
        ref="refs/heads/main",
        error_origin=StandardExecution.ErrorOrigin.STANDARD,
        **kwargs,
    ):
        standard = standard or self.standard
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            event_type=event_type,
            ref=ref,
            status=status,
            error_origin=error_origin,
            **kwargs,
        )

    def _run(self, *rows, error=""):
        """Hand one finished run made of ``rows`` to the policy."""
        statuses = [r.status for r in rows]
        self.policy.handle(
            self._event(
                rows,
                passed=statuses.count(StandardExecution.Status.PASSED),
                failed=statuses.count(StandardExecution.Status.FAILED),
                errored=statuses.count(StandardExecution.Status.ERROR),
                error=error,
            )
        )

    def _errored(self, **kwargs):
        return self._result(StandardExecution.Status.ERROR, **kwargs)

    def _passed(self, **kwargs):
        return self._result(StandardExecution.Status.PASSED, **kwargs)

    def _notices(self):
        return Notification.objects.filter(kind="grade.unverified")

    def test_notice_on_the_transition_only(self):
        """Passed before, errored now: one critical notice naming the
        standard, linking to the project page. The run also passed another
        standard, so the run as a whole could be evaluated."""
        self._run(self._passed())
        other = self._standard("Pinned CI", critical=False)
        user = baker.make("app.User")
        errored = self._errored(
            details={"error": True},
            message="Traceback (most recent call last):\nKeyError: 'GITHUB_TOKEN'",
            triggered_by_user=user,
        )
        self._run(errored, self._passed(standard=other))

        n = Notification.objects.get()
        self.assertEqual(n.kind, "grade.unverified")
        self.assertEqual(n.severity, "critical")
        self.assertEqual(n.subject, "Acme")
        self.assertEqual(n.title, "Could not verify No secrets")
        self.assertEqual(n.body, "Grade F until it passes again on main: KeyError: 'GITHUB_TOKEN'")
        self.assertEqual(n.url, reverse("project_detail", args=[self.project.pk]) + "#compliance")
        self.assertEqual(n.context["project_id"], str(self.project.pk))
        self.assertEqual(n.context["standard_ids"], [str(self.standard.pk)])
        self.assertEqual(n.context["execution_ids"], [str(errored.pk)])
        self.assertEqual(n.context["trigger"], "push")
        self.assertEqual(n.triggered_by_user_ids, [str(user.pk)])
        self.defer.assert_called_once_with(notification_id=str(n.pk))

    def test_first_error_with_no_history_notifies(self):
        """No previous counting result is a transition too."""
        self._run(self._errored())
        self.assertEqual(self._notices().count(), 1)

    def test_repeat_error_silent(self):
        self._run(self._errored())
        self._run(self._errored())
        self._run(self._errored())
        self.assertEqual(self._notices().count(), 1)

    def test_after_a_pass_the_next_error_notifies_again(self):
        self._run(self._errored())
        self._run(self._passed())
        self.assertEqual(self._notices().count(), 1)
        self._run(self._errored())
        self.assertEqual(self._notices().count(), 2)

    def test_after_a_fail_the_next_error_notifies(self):
        """Failed is a verdict; errored is the lack of one."""
        self._run(self._result(StandardExecution.Status.FAILED))
        self._run(self._errored())
        self.assertEqual(self._notices().count(), 1)

    def test_flipping_the_mark_onto_an_already_errored_attachment_is_silent(self):
        """Not critical when it errored, marked critical afterwards: no run,
        so nothing; the page shows "F — could not verify" on its own. The
        next error is a repeat, still silent."""
        ProjectStandard.objects.filter(project=self.project).update(level="high")
        self._run(self._errored())
        self.assertFalse(self._notices().exists())

        ProjectStandard.objects.filter(project=self.project).update(level="critical")
        self._run(self._errored())
        self.assertFalse(self._notices().exists())

    def test_a_run_on_another_branch_never_notifies(self):
        self._run(self._passed())
        self._run(self._errored(event_type="pull_request", ref="refs/pull/7/head"))
        self._run(self._errored(event_type="push", ref="refs/heads/feature"))
        self.assertFalse(self._notices().exists())

    def test_a_branch_scoped_standard_alerts_on_its_own_branch(self):
        """The home branch is the Branch/Tag Filter's literal branch when
        there is one; the body names it."""
        self.standard.criteria = {"ref": "release"}
        self.standard.save()
        self._run(self._errored(ref="refs/heads/main"))
        self.assertFalse(self._notices().exists())
        self._run(self._errored(ref="refs/heads/release"))
        n = self._notices().get()
        self.assertEqual(n.body, "Grade F until it passes again on release")

    def test_previous_pr_error_is_not_the_previous_result(self):
        """A PR run that errored does not count as "already errored": the
        first home-branch error after it still notifies."""
        self._run(self._errored(event_type="pull_request", ref="refs/pull/7/head"))
        self._run(self._errored())
        self.assertEqual(self._notices().count(), 1)

    def test_platform_errors_never_notify(self):
        self._run(self._passed())
        self._run(self._errored(error_origin=StandardExecution.ErrorOrigin.PLATFORM))
        self._run(self._errored(error_origin=StandardExecution.ErrorOrigin.PLATFORM), error="boom")
        self.assertFalse(self._notices().exists())

    def test_platform_error_keeps_the_previous_result(self):
        """Our outage in between does not reset the dedupe: errored, then a
        platform error, then errored again is still a repeat."""
        self._run(self._errored())
        self._run(self._errored(error_origin=StandardExecution.ErrorOrigin.PLATFORM))
        self._run(self._errored())
        self.assertEqual(self._notices().count(), 1)

    def test_non_critical_errors_never_notify(self):
        other = self._standard("Pinned CI", critical=False)
        self._run(self._passed(standard=other))
        self._run(self._errored(standard=other))
        self.assertFalse(self._notices().exists())

    def test_disabled_or_draft_standard_never_notifies(self):
        self.standard.enabled = False
        self.standard.save()
        self._run(self._errored())
        self.standard.enabled = True
        self.standard.draft = True
        self.standard.save()
        self._run(self._errored())
        self.assertFalse(self._notices().exists())

    def test_one_notice_per_project_names_every_unverified_standard(self):
        other = self._standard("Pinned CI", critical=True)
        self._run(self._errored(), self._errored(standard=other))
        n = self._notices().get()
        self.assertEqual(n.title, "Could not verify No secrets, Pinned CI")
        self.assertTrue(n.body.startswith("Grade F until they pass again on main"), n.body)
        self.assertEqual(
            set(n.context["standard_ids"]), {str(self.standard.pk), str(other.pk)}
        )

    def test_audience_is_every_member(self):
        """Owner, admin and member of the workspace all hear it; a member of
        another workspace does not."""
        users = {
            role: str(baker.make("app.Membership", tenant=self.tenant, role=role).user_id)
            for role in ("owner", "admin", "member")
        }
        baker.make("app.Membership", role="owner")  # another workspace
        self._run(self._errored())
        n = self._notices().get()
        self.assertEqual(route_for(n.kind).recipients(n), sorted(users.values()))

    def test_published_event_reaches_it(self):
        event_bus.clear()
        subscribers.register()
        row = self._errored(details={"error": "boom"})
        event_bus.publish(self._event([row], errored=1))
        kinds = sorted(Notification.objects.values_list("kind", flat=True))
        # "GitGrit could not evaluate" fires beside it: different facts.
        self.assertEqual(kinds, ["grade.unverified", "run.failed"])


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
