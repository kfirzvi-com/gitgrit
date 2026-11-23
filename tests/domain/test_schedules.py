"""Schedules (``app.domain.schedules``): cron schedules read in a time zone,
said in words, what runs an attached standard, and which standards a check
runs or carries (``scoring.CheckPlan``)."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from app.domain import schedules, scoring
from app.domain.importance import Importance

S = scoring.StandardRunStatus


class CronScheduleTests(SimpleTestCase):
    def test_a_schedule_is_five_fields_with_spaces_normalised(self):
        assert schedules.CronSchedule.parse("  0   9 * *  1-5 ").expression == "0 9 * * 1-5"

    def test_macros_are_spelled_out(self):
        assert schedules.CronSchedule.parse("@daily").expression == "0 0 * * *"
        assert schedules.CronSchedule.parse("@Weekly").expression == "0 0 * * 0"

    def test_anything_else_is_refused(self):
        for bad in ("", "0 9 * *", "0 9 * * * *", "61 * * * *", "every day"):
            with self.subTest(bad=bad), self.assertRaises(schedules.InvalidSchedule):
                schedules.CronSchedule.parse(bad)

    def test_an_unknown_time_zone_is_refused(self):
        with self.assertRaises(schedules.InvalidSchedule):
            schedules.CronSchedule.parse("0 9 * * *", "Mars/Olympus")

    def test_next_runs_are_read_in_its_time_zone(self):
        after = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
        runs = schedules.CronSchedule.parse("0 9 * * *", "Asia/Jerusalem").next_runs(after, 2)
        assert [r.astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%d %H:%M") for r in runs] == ["24 09:00", "25 09:00"]
        assert runs[0].astimezone(timezone.utc).hour == 7

    def test_the_shortest_gap_says_how_often_it_runs(self):
        after = datetime(2026, 11, 23, tzinfo=timezone.utc)
        assert schedules.CronSchedule.parse("*/15 * * * *").shortest_gap(after).total_seconds() == 900


class CronDescriptionTests(SimpleTestCase):
    def test_common_schedules_read_as_people_say_them(self):
        cases = {
            "0 9 * * *": "Every day at 09:00",
            "*/15 * * * *": "Every 15 minutes",
            "30 2 * * 1-5": "At 02:30 on weekdays",
            "0 12 * * 0,6": "At 12:00 on weekends",
            "0 6 1 * *": "At 06:00 on day 1 of the month",
            "0 9,17 * * *": "Every day at 09:00 and 17:00",
            "0 * * * *": "Every hour",
            "15 */6 * * *": "Every 6 hours at :15",
            "0 9 * * 1,3,5": "At 09:00 on Monday, Wednesday and Friday",
            "0 9 * * MON": "At 09:00 on Monday",
            "*/5 9-17 * * 1-5": "Every 5 minutes from 09:00 to 17:59 on weekdays",
            "0 8 * 1-3 *": "Every day at 08:00 in January through March",
            "0 3 15 * 0": "At 03:00 on day 15 of the month or on Sunday",
        }
        for cron, text in cases.items():
            with self.subTest(cron=cron):
                assert schedules.CronDescription(schedules.CronSchedule.parse(cron)).text == text


class StandardScheduleTests(SimpleTestCase):
    def test_on_changes_keeps_no_schedule_even_a_half_typed_one(self):
        schedule = schedules.StandardSchedule.parse("changes", "0 9 *")
        assert (schedule.trigger, schedule.expression, schedule.runs_on_changes) == (
            schedules.RunTrigger.CHANGES, "", True
        )
        assert schedule.next_run_after(datetime.now(timezone.utc)) is None

    def test_a_schedule_needs_a_schedule(self):
        with self.assertRaises(schedules.InvalidSchedule):
            schedules.StandardSchedule.parse("schedule", "")

    def test_schedule_only_does_not_run_on_changes_and_both_does(self):
        assert not schedules.StandardSchedule.parse("schedule", "@daily").runs_on_changes
        assert schedules.StandardSchedule.parse("both", "@daily").runs_on_changes

    def test_an_unknown_trigger_is_refused(self):
        with self.assertRaises(schedules.InvalidSchedule):
            schedules.StandardSchedule.parse("sometimes", "@daily")

    def test_the_trigger_is_read_back_from_what_is_stored(self):
        assert schedules.RunTrigger.of(True, False) is schedules.RunTrigger.CHANGES
        assert schedules.RunTrigger.of(False, True) is schedules.RunTrigger.SCHEDULE
        assert schedules.RunTrigger.of(True, True) is schedules.RunTrigger.BOTH


def _attached(sid, scheduled_only=False):
    return scoring.AttachedStandard(sid, enabled=True, draft=False, matches_criteria=True, scheduled_only=scheduled_only)


class CheckPlanTests(SimpleTestCase):
    def test_a_change_on_the_default_branch_carries_the_scheduled_only_standards(self):
        plan = scoring.CheckPlan.for_change([_attached("a"), _attached("llm", True)], on_default_branch=True)
        assert (plan.run, plan.carried, plan.expected) == (("a",), ("llm",), ("a", "llm"))

    def test_a_change_on_another_branch_leaves_them_out(self):
        plan = scoring.CheckPlan.for_change([_attached("a"), _attached("llm", True)], on_default_branch=False)
        assert (plan.run, plan.carried) == (("a",), ())

    def test_a_scheduled_run_carries_the_rest_of_the_current_score_that_still_applies(self):
        plan = scoring.CheckPlan.for_schedule(due=["llm"], current=["a", "b", "llm", "gone"], applying=["a", "b", "llm"])
        assert (plan.run, plan.carried) == (("llm",), ("a", "b"))

    def test_a_scheduled_run_with_no_current_score_expects_the_due_standards_alone(self):
        plan = scoring.CheckPlan.for_schedule(due=["llm"], current=[], applying=["a", "llm"])
        assert (plan.run, plan.carried) == (("llm",), ())


def _result(sid, status=S.PASSED, score=100, eid=""):
    return scoring.StandardRunResult(sid, sid.upper(), status, score, Importance.MAJOR, eid or sid)


class CarriedResultsTests(SimpleTestCase):
    def test_a_check_is_scored_from_its_own_results_and_the_carried_ones(self):
        run = scoring.CheckRun(
            commit_sha="c1",
            expected=scoring.ExpectedStandards(("a", "llm")),
            results=(_result("a", score=100),),
            carried=(_result("llm", S.FAILED, 50, "old"),),
        )
        assert run.decide().score.value == 75
        assert [r.standard_id for r in run.latest_results] == ["a", "llm"]
        assert run.carried_execution_ids == {"old"}
        assert run.never_ran_ids == []

    def test_its_own_result_beats_a_carried_one(self):
        run = scoring.CheckRun(
            commit_sha="c1",
            expected=scoring.ExpectedStandards(("a",)),
            results=(_result("a", score=100, eid="new"),),
            carried=(_result("a", S.FAILED, 0, "old"),),
        )
        assert run.decide().score.value == 100
        assert [r.execution_id for r in run.latest_results] == ["new"]

    def test_nothing_to_carry_leaves_it_not_run(self):
        run = scoring.CheckRun(commit_sha="c1", expected=scoring.ExpectedStandards(("a", "llm")), results=(_result("a"),))
        assert run.decide().score.value is None
        assert run.never_ran_ids == ["llm"]
