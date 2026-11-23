"""Scheduled standards end to end: setting a schedule on an attachment, the
scheduler queueing due runs on the default branch, a push carrying a
scheduled-only standard's newest result, and the project score keeping every
standard whatever ran it (``app.domain.schedules``)."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application import project_management, scoring
from app.application.schedules import StandardScheduler
from app.application.standard_runs import enqueue_for_event
from app.domain import schedules
from app.domain.events import DomainEvent
from app.domain.models import CommitCheck, ProjectStandard, StandardExecution
from tests.support import defer_patch

Status = StandardExecution.Status


class Fixture(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=self.tenant, platform="github")
        self.project = baker.make(
            "app.Project", tenant=self.tenant, platform="github", platform_connection=connection,
            external_id="42", default_branch="main", languages=[],
        )
        self.cheap = self._attach("Cheap")
        self.llm = self._attach("LLM")
        self.now = timezone.now()

    def _attach(self, name):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, name=name, enabled=True, draft=False,
            criteria={"events": ["push", "pull_request"]},
        )
        self.project.standards.add(standard)
        return standard

    def schedule(self, standard, trigger="schedule", cron="0 9 * * *"):
        attachment = ProjectStandard.objects.get(project=self.project, standard=standard)
        attachment.apply_schedule(schedules.StandardSchedule.parse(trigger, cron, "UTC"), self.now)
        attachment.save()
        return attachment

    def finish(self, check, status=Status.PASSED, score=100):
        check.executions.update(status=status, score=score)
        return scoring.score_check(check)

    def push(self, ref="refs/heads/main", sha="c2"):
        event = DomainEvent(event_type="push", platform="github", external_project_id="42", ref=ref, commit_sha=sha)
        with defer_patch():
            enqueue_for_event(event)
        return CommitCheck.objects.filter(project=self.project).order_by("-created_at").first()


class SettingSchedulesTests(Fixture):
    def test_saving_the_table_sets_a_schedule_due_at_its_next_time(self):
        project_management.set_project_standards(
            self.project, [self.cheap.pk, self.llm.pk],
            schedules={str(self.llm.pk): ("schedule", "0 9 * * 1-5", "Asia/Jerusalem")},
        )
        attachment = ProjectStandard.objects.get(project=self.project, standard=self.llm)
        assert (attachment.runs_on_changes, attachment.schedule, attachment.schedule_time_zone) == (
            False, "0 9 * * 1-5", "Asia/Jerusalem"
        )
        assert attachment.next_scheduled_run_at > timezone.now()

    def test_a_bad_schedule_names_the_standard_and_writes_nothing(self):
        with self.assertRaisesMessage(schedules.InvalidSchedule, "LLM:"):
            project_management.set_project_standards(
                self.project, [self.cheap.pk], schedules={str(self.llm.pk): ("schedule", "every day")},
            )
        assert self.project.standards.count() == 2

    def test_back_to_changes_clears_the_schedule(self):
        self.schedule(self.llm)
        project_management.set_project_standards(
            self.project, [self.cheap.pk, self.llm.pk], schedules={str(self.llm.pk): ("changes", "", "")},
        )
        attachment = ProjectStandard.objects.get(project=self.project, standard=self.llm)
        assert (attachment.runs_on_changes, attachment.schedule, attachment.next_scheduled_run_at) == (True, "", None)


class SchedulerTests(Fixture):
    def due(self, attachment):
        attachment.next_scheduled_run_at = timezone.now() - timedelta(minutes=1)
        attachment.save()

    def test_a_due_standard_runs_on_the_default_branch_and_moves_to_its_next_time(self):
        self.due(self.schedule(self.llm))
        with defer_patch() as configure:
            assert StandardScheduler().run_due() == 1
        configure.return_value.defer.assert_called_once()
        check = CommitCheck.objects.get(project=self.project)
        assert (check.event_type, check.branch) == ("schedule", "main")
        assert list(check.executions.values_list("standard_id", flat=True)) == [self.llm.pk]
        assert ProjectStandard.objects.get(standard=self.llm).next_scheduled_run_at > timezone.now()

    def test_nothing_due_runs_nothing(self):
        self.schedule(self.llm)
        with defer_patch():
            assert StandardScheduler().run_due() == 0
        assert not CommitCheck.objects.exists()

    def test_a_disabled_standard_is_not_run_but_still_moves_on(self):
        self.due(self.schedule(self.llm))
        self.llm.enabled = False
        self.llm.save()
        with defer_patch():
            assert StandardScheduler().run_due() == 0
        assert ProjectStandard.objects.get(standard=self.llm).next_scheduled_run_at > timezone.now()

    def test_a_scheduled_run_carries_the_rest_of_the_score_and_moves_it(self):
        self.schedule(self.llm)
        first = self.push(sha="c1")  # cheap runs, llm carried (nothing yet)
        with defer_patch():
            from app.application.standard_runs import enqueue_manual_run
            enqueue_manual_run(self.project, [self.llm])
        self.finish(first)
        manual = CommitCheck.objects.filter(event_type="manual").get()
        manual.commit_sha = "c1"
        manual.save()
        self.finish(manual, Status.FAILED, 0)

        self.due(ProjectStandard.objects.get(standard=self.llm))
        with defer_patch():
            StandardScheduler().run_due()
        scheduled = CommitCheck.objects.get(event_type="schedule")
        scheduled.commit_sha = "c1"
        scheduled.save()
        assert scheduled.carried_standard_ids == [str(self.cheap.pk)]
        score = self.finish(scheduled, Status.PASSED, 100)

        assert score.value == 100
        assert scoring.project_score(self.project).pk == score.pk


class PushCarriesScheduledTests(Fixture):
    def test_a_push_to_the_default_branch_skips_a_scheduled_only_standard_and_carries_its_result(self):
        self.schedule(self.llm)
        earlier = baker.make("app.CommitCheck", project=self.project, branch="main", commit_sha="c1", event_type="schedule")
        baker.make(
            "app.StandardExecution", project=self.project, standard=self.llm, standard_name="LLM",
            commit_check=earlier, status=Status.FAILED, score=40, event_type="schedule",
        )
        check = self.push()
        assert list(check.executions.values_list("standard_id", flat=True)) == [self.cheap.pk]
        assert check.carried_standard_ids == [str(self.llm.pk)]

        score = self.finish(check, Status.PASSED, 100)

        assert score.value == 70
        assert set(score.executions.values_list("standard_name", flat=True)) == {"Cheap", "LLM"}

    def test_a_push_to_another_branch_leaves_it_out(self):
        self.schedule(self.llm)
        check = self.push(ref="refs/heads/feature/x")
        assert check.carried_standard_ids == []
        assert check.expected_standard_ids == [str(self.cheap.pk)]
        assert self.finish(check).value == 100

    def test_changes_and_schedule_runs_on_the_push_too(self):
        self.schedule(self.llm, trigger="both")
        check = self.push()
        assert check.executions.count() == 2
        assert check.carried_standard_ids == []

    def test_a_push_matching_only_scheduled_standards_runs_nothing(self):
        self.schedule(self.llm)
        self.schedule(self.cheap)
        self.push()
        assert not CommitCheck.objects.exists()


class RescoreCarriersTests(Fixture):
    def test_a_check_that_finishes_after_a_newer_one_carried_from_it_rescores_that_one(self):
        self.schedule(self.llm)
        slow = baker.make(
            "app.CommitCheck", project=self.project, branch="main", commit_sha="c1", event_type="schedule",
            expected_standard_ids=[str(self.llm.pk)],
        )
        llm_run = baker.make(
            "app.StandardExecution", project=self.project, standard=self.llm, standard_name="LLM",
            commit_check=slow, status=Status.RUNNING, event_type="schedule",
        )
        push = self.push(sha="c1")
        first = self.finish(push, Status.PASSED, 100)
        assert first.value is None  # the LLM has no result yet

        llm_run.status, llm_run.score = Status.PASSED, 60
        llm_run.save()
        scoring.score_check(slow)

        assert scoring.project_score(self.project).value == 80
