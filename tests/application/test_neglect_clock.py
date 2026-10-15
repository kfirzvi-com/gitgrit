"""The neglect clock on the attachment (``ProjectStandard.first_failed_at``):
how the engine keeps it after each result, and how the release-day
migration starts it. One test per rule; the name says which.
"""
import uuid
from datetime import timedelta
from importlib import import_module

import pytest
from django.apps import apps
from django.test import TestCase
from django.utils import timezone
from model_bakery import baker

from app import tasks
from app.domain.models import ProjectStandard, StandardExecution
from tests.application.test_standard_runs import FAILED, PASSED, _mocked_runner

Status = StandardExecution.Status
Origin = StandardExecution.ErrorOrigin

ERRORED = {"passed": False, "score": 0, "message": "boom", "details": {"error": True}}
PLATFORM_ERRORED = {**ERRORED, "error_origin": "platform"}


def _run_with(result):
    """A runner that returns ``result`` for every standard."""
    return lambda _code, _config: dict(result)


@pytest.mark.django_db
class EngineKeepsTheClockTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self.standard = baker.make("app.Standard", tenant=self.tenant, name="Old")
        self.project.standards.add(self.standard)

    def _attachment(self):
        return ProjectStandard.objects.get(project=self.project, standard=self.standard)

    def _set_clock(self, when):
        ProjectStandard.objects.filter(pk=self._attachment().pk).update(first_failed_at=when)

    def _execution(self, event_type="manual", ref=""):
        return baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=self.standard,
            standard_name=self.standard.name,
            event_type=event_type,
            ref=ref,
            status=Status.RUNNING,
        )

    def _finish(self, execution, result):
        with _mocked_runner(_run_with(result)):
            tasks.run_standards.func(
                project_id=str(self.project.pk), execution_ids=[str(execution.pk)]
            )
        execution.refresh_from_db()
        return execution

    def test_the_clock_starts_at_the_first_failure_on_the_default_branch(self):
        """Null before; set at the failing run's time; a later failure keeps
        the first time."""
        assert self._attachment().first_failed_at is None
        before = timezone.now()

        self._finish(self._execution(event_type="push", ref="refs/heads/main"), FAILED)

        started = self._attachment().first_failed_at
        assert started is not None and started >= before

        self._finish(self._execution(), FAILED)
        assert self._attachment().first_failed_at == started

    def test_a_standard_origin_error_keeps_the_clock_running(self):
        """An error inside the standard's own run neither starts a new
        clock nor clears one (P10): only a pass resets it."""
        started = timezone.now() - timedelta(days=15)
        self._set_clock(started)

        execution = self._finish(self._execution(), ERRORED)

        assert execution.status == Status.ERROR
        assert execution.error_origin == Origin.STANDARD
        assert self._attachment().first_failed_at == started
        # And with no clock running, the error starts one like a failure.
        self._set_clock(None)
        self._finish(self._execution(), ERRORED)
        assert self._attachment().first_failed_at is not None

    def test_a_platform_error_does_not_touch_the_clock(self):
        """GitGrit's own failure keeps whatever the clock says: a running
        clock keeps running, an idle one stays idle."""
        started = timezone.now() - timedelta(days=15)
        self._set_clock(started)
        execution = self._finish(self._execution(), PLATFORM_ERRORED)
        assert execution.error_origin == Origin.PLATFORM
        assert self._attachment().first_failed_at == started

        self._set_clock(None)
        self._finish(self._execution(), PLATFORM_ERRORED)
        assert self._attachment().first_failed_at is None

    def test_a_pass_resets_the_clock(self):
        self._set_clock(timezone.now() - timedelta(days=15))

        self._finish(self._execution(), PASSED)

        assert self._attachment().first_failed_at is None

    def test_a_run_on_another_branch_does_not_touch_the_clock(self):
        """Runs on other branches (a pull request, a feature push) never
        move the grade, so they never move the clock either: a failing one
        starts nothing and a passing one clears nothing."""
        self._finish(self._execution(event_type="pull_request", ref="feature"), FAILED)
        assert self._attachment().first_failed_at is None

        started = timezone.now() - timedelta(days=15)
        self._set_clock(started)
        self._finish(self._execution(event_type="push", ref="refs/heads/feature"), PASSED)
        assert self._attachment().first_failed_at == started

    def test_a_branch_scoped_standard_keeps_its_clock_on_its_own_branch(self):
        """A standard whose Branch/Tag Filter names ``develop`` is graded on
        develop, so only develop runs move its clock."""
        self.standard.criteria = {"events": ["push"], "ref": "develop"}
        self.standard.save()

        self._finish(self._execution(event_type="push", ref="refs/heads/main"), FAILED)
        assert self._attachment().first_failed_at is None

        self._finish(self._execution(event_type="push", ref="refs/heads/develop"), FAILED)
        started = self._attachment().first_failed_at
        assert started is not None

        self._finish(self._execution(event_type="manual", ref=""), PASSED)
        assert self._attachment().first_failed_at == started

        self._finish(self._execution(event_type="manual", ref="develop"), PASSED)
        assert self._attachment().first_failed_at is None

    def test_detach_and_reattach_resets_the_clock(self):
        """Detaching deletes the attachment row, clock and all (P11)."""
        self._set_clock(timezone.now() - timedelta(days=15))

        self.project.standards.remove(self.standard)
        self.project.standards.add(self.standard)

        assert self._attachment().first_failed_at is None

    def _commit_run(self, status, *, committed_ago, created_ago=timedelta(0), running=False):
        """A home-branch run on a commit made ``committed_ago`` ago; finished
        with ``status`` already, or still running when ``running``."""
        now = timezone.now()
        check = baker.make(
            "app.CommitCheck",
            project=self.project,
            branch="main",
            commit_sha=uuid.uuid4().hex[:40],
            committed_at=now - committed_ago,
        )
        row = baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=self.standard,
            standard_name=self.standard.name,
            event_type="manual",
            ref="",
            status=Status.RUNNING if running else status,
            commit_check=check,
        )
        StandardExecution.objects.filter(pk=row.pk).update(created_at=now - created_ago)
        return row

    def test_rerunning_an_older_passing_commit_does_not_clear_the_clock(self):
        """The grade follows the newest commit, so the clock does too: a
        newer commit still fails, so an old commit passing again is no fix."""
        started = timezone.now() - timedelta(days=15)
        self._set_clock(started)
        self._commit_run(Status.FAILED, committed_ago=timedelta(hours=1), created_ago=timedelta(hours=1))
        old = self._commit_run(Status.PASSED, committed_ago=timedelta(days=3), running=True)

        self._finish(old, PASSED)

        assert self._attachment().first_failed_at == started

    def test_rerunning_an_older_failing_commit_does_not_start_the_clock(self):
        self._commit_run(Status.PASSED, committed_ago=timedelta(hours=1), created_ago=timedelta(hours=1))
        old = self._commit_run(Status.FAILED, committed_ago=timedelta(days=3), running=True)

        self._finish(old, FAILED)

        assert self._attachment().first_failed_at is None


@pytest.mark.django_db
class ReleaseDayBackfillTests(TestCase):
    """Migration 0049 starts the clock, at migration time, only for the
    attachments whose latest counting home-branch result is failing or a
    standard-origin error; it never dates a clock from a past failure."""

    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make("app.Project", tenant=self.tenant, default_branch="main")
        self._clock = timezone.now() - timedelta(days=10)
        self.migration = import_module("app.migrations.0049_neglect_clock")

    def _attach(self, name, **kwargs):
        kwargs.setdefault("enabled", True)
        kwargs.setdefault("draft", False)
        standard = baker.make("app.Standard", tenant=self.tenant, name=name, **kwargs)
        self.project.standards.add(standard)
        return standard

    def _run(self, standard, status, *, event_type="manual", ref="", error_origin=Origin.STANDARD):
        self._clock += timedelta(minutes=1)
        row = baker.make(
            "app.StandardExecution",
            project=self.project,
            standard=standard,
            standard_name=standard.name,
            event_type=event_type,
            ref=ref,
            status=status,
            error_origin=error_origin,
        )
        StandardExecution.objects.filter(pk=row.pk).update(created_at=self._clock)
        return row

    def _clocks(self):
        return {
            row.standard.name: row.first_failed_at
            for row in ProjectStandard.objects.filter(project=self.project).select_related("standard")
        }

    def test_backfill_starts_the_clock_only_for_currently_failing_counting_attachments(self):
        failing = self._attach("failing")
        self._run(failing, Status.FAILED, event_type="push", ref="refs/heads/main")
        errored = self._attach("errored")
        self._run(errored, Status.ERROR)
        passing = self._attach("passing")
        self._run(passing, Status.FAILED)
        self._run(passing, Status.PASSED)  # latest counting row passes
        recovered_then_platform = self._attach("platform-latest")
        self._run(recovered_then_platform, Status.PASSED)
        self._run(recovered_then_platform, Status.ERROR, error_origin=Origin.PLATFORM)
        pr_only = self._attach("pr-only")
        self._run(pr_only, Status.FAILED, event_type="pull_request", ref="feature")
        scoped = self._attach("scoped", criteria={"events": ["push"], "ref": "develop"})
        self._run(scoped, Status.PASSED, event_type="push", ref="refs/heads/main")
        self._run(scoped, Status.FAILED, event_type="push", ref="refs/heads/develop")
        scoped_fixed = self._attach("scoped-fixed", criteria={"events": ["push"], "ref": "develop"})
        self._run(scoped_fixed, Status.PASSED, event_type="push", ref="refs/heads/develop")
        self._run(scoped_fixed, Status.FAILED, event_type="push", ref="refs/heads/main")
        running = self._attach("running")
        self._run(running, Status.PASSED)
        self._run(running, Status.RUNNING)
        disabled = self._attach("disabled", enabled=False)
        self._run(disabled, Status.FAILED)
        draft = self._attach("draft", draft=True)
        self._run(draft, Status.FAILED)
        never_ran = self._attach("never-ran")
        before = timezone.now()

        self.migration.start_clocks_for_failing_attachments(apps, None)

        clocks = self._clocks()
        started = {name for name, when in clocks.items() if when is not None}
        assert started == {"failing", "errored", "scoped"}
        # The clock starts at release, never from the past failure.
        assert all(clocks[name] >= before for name in started)
        assert never_ran.name in clocks
