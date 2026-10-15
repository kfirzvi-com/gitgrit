"""``grade_for_project``: which execution rows become the Results the grade
is decided over. One test per gathering rule; the name says which.
"""
from datetime import timedelta

import pytest
from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app.application.grading_service import grade_for_project
from app.domain.grading import NO_GRADE
from app.domain.models import ProjectStandard, StandardExecution

Status = StandardExecution.Status
Origin = StandardExecution.ErrorOrigin


@pytest.mark.django_db
class TestGradeForProject(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self._clock = timezone.now() - timedelta(hours=1)

    def _standard(self, name="s", **kwargs):
        kwargs.setdefault("enabled", True)
        kwargs.setdefault("draft", False)
        standard = baker.make("app.Standard", tenant=self.tenant, name=name, **kwargs)
        self.project.standards.add(standard)
        return standard

    def _run(
        self,
        standard,
        status=Status.PASSED,
        *,
        event_type="manual",
        ref="",
        error_origin=Origin.STANDARD,
        project=None,
    ):
        """One execution row, each newer than the last."""
        self._clock += timedelta(minutes=1)
        row = baker.make(
            "app.StandardExecution",
            project=project or self.project,
            standard=standard,
            standard_name=standard.name,
            event_type=event_type,
            ref=ref,
            status=status,
            error_origin=error_origin,
        )
        StandardExecution.objects.filter(pk=row.pk).update(created_at=self._clock)
        return row

    def test_letter_from_pass_rate(self):
        a, b, c = self._standard("a"), self._standard("b"), self._standard("c")
        self._run(a)
        self._run(b)
        self._run(c, Status.FAILED)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "C"
        assert grading.grade.reason == "1 standard failing"
        assert [ex.standard_id for ex in grading.executions] == [a.pk, b.pk, c.pk]
        assert grading.not_evaluated == []

    def test_running_rows_do_not_count(self):
        """The previous finished result stays while a newer run is in flight."""
        s = self._standard()
        self._run(s, Status.PASSED)
        running = self._run(s, Status.RUNNING)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "A+"
        assert [ex.pk for ex in grading.executions] != [running.pk]

    def test_unattached_disabled_and_draft_do_not_count(self):
        attached = self._standard("attached")
        disabled = self._standard("disabled", enabled=False)
        draft = self._standard("draft", draft=True)
        unattached = baker.make("app.Standard", tenant=self.tenant, name="unattached")
        self._run(attached)
        for s in (disabled, draft, unattached):
            self._run(s, Status.FAILED)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "A+"
        assert [ex.standard_id for ex in grading.executions] == [attached.pk]
        assert grading.not_evaluated == []

    def test_home_branch_runs_only(self):
        """A push to the default branch and a manual run with an empty ref
        count; a push to another branch, a pull request from one and a
        manual run on one never do, however new they are."""
        pushed = self._standard("pushed")
        manual = self._standard("manual")
        self._run(pushed, Status.PASSED, event_type="push", ref="refs/heads/main")
        self._run(manual, Status.PASSED, event_type="manual", ref="")
        # Newer, failing, but not on the home branch: none of these count.
        self._run(pushed, Status.FAILED, event_type="push", ref="refs/heads/feature")
        self._run(pushed, Status.FAILED, event_type="pull_request", ref="feature")
        self._run(manual, Status.FAILED, event_type="manual", ref="develop")

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "A+"
        assert {ex.status for ex in grading.executions} == {Status.PASSED}

    def test_a_branch_scoped_standard_grades_on_its_own_branch(self):
        """A standard whose Branch/Tag Filter names ``develop`` has develop
        as its home branch: its develop runs count and its default-branch
        runs do not (the plan's P13, "never graded", is superseded by
        main's home-branch rule)."""
        scoped = self._standard("scoped", criteria={"events": ["push"], "ref": "develop"})
        self._run(scoped, Status.PASSED, event_type="manual", ref="")
        self._run(scoped, Status.PASSED, event_type="push", ref="refs/heads/main")

        grading = grade_for_project(self.project)
        assert grading.not_evaluated == [scoped]
        assert grading.not_evaluated[0].home_branch == "develop"

        failing = self._run(scoped, Status.FAILED, event_type="push", ref="refs/heads/develop")

        grading = grade_for_project(self.project)
        assert grading.grade.letter == "D"
        assert [ex.pk for ex in grading.executions] == [failing.pk]

    def test_the_newest_commit_wins_not_the_newest_run(self):
        """Checking an old commit again must not change the grade."""
        s = self._standard()
        newer = baker.make(
            "app.CommitCheck", project=self.project, branch="main", commit_sha="b" * 40,
            committed_at=timezone.now() - timedelta(days=1),
        )
        older = baker.make(
            "app.CommitCheck", project=self.project, branch="main", commit_sha="a" * 40,
            committed_at=timezone.now() - timedelta(days=2),
        )
        on_newer = self._run(s, Status.PASSED)
        StandardExecution.objects.filter(pk=on_newer.pk).update(commit_check=newer)
        rerun_of_older = self._run(s, Status.FAILED)
        StandardExecution.objects.filter(pk=rerun_of_older.pk).update(commit_check=older)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "A+"
        assert [ex.pk for ex in grading.executions] == [on_newer.pk]

    def test_pr_only_history_is_not_evaluated(self):
        s = self._standard()
        self._run(s, Status.FAILED, event_type="pull_request", ref="feature")

        grading = grade_for_project(self.project)

        assert grading.grade.letter == NO_GRADE
        assert grading.not_evaluated == [s]
        assert grading.not_evaluated[0].home_branch == "main"

    def test_platform_errors_keep_the_previous_result(self):
        """A stale sweep, job failure or sandbox error never changes a grade:
        the previous counting result stays, through any number of them."""
        s = self._standard()
        ok = self._run(s, Status.PASSED)
        self._run(s, Status.ERROR, error_origin=Origin.PLATFORM)
        self._run(s, Status.ERROR, error_origin=Origin.PLATFORM)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "A+"
        assert [ex.pk for ex in grading.executions] == [ok.pk]

    def test_only_platform_errors_means_not_evaluated(self):
        s = self._standard()
        self._run(s, Status.ERROR, error_origin=Origin.PLATFORM)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == NO_GRADE
        assert grading.not_evaluated == [s]

    def test_skipped_rows_are_ignored(self):
        s = self._standard()
        ok = self._run(s, Status.PASSED)
        self._run(s, Status.SKIPPED)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "A+"
        assert [ex.pk for ex in grading.executions] == [ok.pk]

    def test_standard_origin_error_counts_as_not_passed(self):
        s = self._standard()
        self._run(s, Status.PASSED)
        broken = self._run(s, Status.ERROR, error_origin=Origin.STANDARD)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "D"
        assert grading.grade.reason == "1 standard failing"
        assert [ex.pk for ex in grading.executions] == [broken.pk]

    def test_no_results_means_no_grade_and_lists_not_evaluated(self):
        never_ran = self._standard("never ran")
        only_running = self._standard("only running")
        self._run(only_running, Status.RUNNING)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == NO_GRADE
        assert not grading.grade.graded
        assert grading.executions == []
        assert grading.not_evaluated == [never_ran, only_running]

    def test_reason_priority_failing_count_then_perfect(self):
        a, b = self._standard("a"), self._standard("b")
        self._run(a)
        self._run(b)
        assert grade_for_project(self.project).grade.reason == "perfect"

        self._run(b, Status.FAILED)
        assert grade_for_project(self.project).grade.reason == "1 standard failing"

    def test_another_projects_runs_do_not_count(self):
        s = self._standard()
        other = baker.make("app.Project", tenant=self.tenant)
        other.standards.add(s)
        self._run(s, Status.PASSED)
        self._run(s, Status.FAILED, project=other)

        assert grade_for_project(self.project).grade.letter == "A+"


@pytest.mark.django_db
class TestCriticalGate(TestCase):
    """The Critical mark on the attachment gates the grade. One test per
    rule; the name says which."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self._clock = timezone.now() - timedelta(hours=1)

    def _attach(self, project, standard, *, critical=False):
        project.standards.add(standard)
        ProjectStandard.objects.filter(project=project, standard=standard).update(
            critical=critical
        )

    def _standard(self, name="s", *, critical=False, project=None, **kwargs):
        kwargs.setdefault("enabled", True)
        kwargs.setdefault("draft", False)
        standard = baker.make("app.Standard", tenant=self.tenant, name=name, **kwargs)
        self._attach(project or self.project, standard, critical=critical)
        return standard

    def _run(self, standard, status=Status.PASSED, *, error_origin=Origin.STANDARD, project=None):
        self._clock += timedelta(minutes=1)
        row = baker.make(
            "app.StandardExecution",
            project=project or self.project,
            standard=standard,
            standard_name=standard.name,
            event_type="manual",
            ref="",
            status=status,
            error_origin=error_origin,
        )
        StandardExecution.objects.filter(pk=row.pk).update(created_at=self._clock)
        return row

    def test_every_attachment_starts_not_critical(self):
        s = baker.make("app.Standard", tenant=self.tenant)
        self.project.standards.add(s)

        row = ProjectStandard.objects.get(project=self.project, standard=s)

        assert row.critical is False
        assert grade_for_project(self.project).critical_standard_ids == frozenset()

    def test_any_critical_fail_is_an_f(self):
        for i in range(9):
            self._run(self._standard(f"ok{i}"))
        gate = self._standard("No secrets", critical=True)
        self._run(gate, Status.FAILED)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "F"
        assert grading.grade.reason == "No secrets failing"
        assert grading.critical_standard_ids == {gate.pk}

    def test_critical_standard_origin_error_is_f_could_not_verify(self):
        gate = self._standard("No secrets", critical=True)
        self._run(self._standard("ok"))
        self._run(gate, Status.ERROR, error_origin=Origin.STANDARD)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "F"
        assert grading.grade.reason == "could not verify No secrets"

    def test_critical_platform_error_keeps_the_previous_result(self):
        gate = self._standard("No secrets", critical=True)
        ok = self._run(gate, Status.PASSED)
        self._run(gate, Status.ERROR, error_origin=Origin.PLATFORM)

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "A+"
        assert [ex.pk for ex in grading.executions] == [ok.pk]

    def test_only_critical_all_passing_is_a_plus(self):
        self._run(self._standard("a", critical=True))
        self._run(self._standard("b", critical=True))

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "A+"
        assert grading.grade.reason == "perfect"

    def test_the_same_standard_gates_one_project_and_not_another(self):
        other = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        shared = self._standard("Shared", critical=True)
        self._attach(other, shared, critical=False)
        self._run(shared, Status.FAILED)
        self._run(shared, Status.FAILED, project=other)

        assert grade_for_project(self.project).grade.letter == "F"
        assert grade_for_project(other).grade.letter == "D"

    def test_result_reads_the_attachments_neglect_clock(self):
        """``first_failed_at`` flows from the attachment into the grade, so a
        standard failing on the default branch for 18 days caps an A at B
        and the reason says so; the clock is not read off any execution."""
        standards = [self._standard(f"s{i}") for i in range(9)]
        old = self._standard("Old")
        for s in standards:
            self._run(s)
        self._run(old, Status.FAILED)
        ProjectStandard.objects.filter(project=self.project, standard=old).update(
            first_failed_at=timezone.now() - timedelta(days=18)
        )

        grading = grade_for_project(self.project)

        assert grading.grade.letter == "B"
        assert grading.grade.reason == "Old failing for 18 days"

    def test_result_reads_the_attachments_current_mark_not_the_snapshot(self):
        """Flipping an attachment to critical while its latest result fails
        shows F on the next read; the row's own snapshot stays as it was."""
        s = self._standard("Late gate")
        row = self._run(s, Status.FAILED)
        assert row.critical is False

        ProjectStandard.objects.filter(project=self.project, standard=s).update(critical=True)

        assert grade_for_project(self.project).grade.letter == "F"
        assert StandardExecution.objects.get(pk=row.pk).critical is False
