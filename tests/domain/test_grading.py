"""The grade rules, decided over ``Result`` values alone (no database).

One test per rule sentence in the grade-gate plan; the name says which.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from app.domain.grading import (
    ERROR,
    FAILED,
    NO_GRADE,
    PASSED,
    PLATFORM_ORIGIN,
    RUNNING,
    SKIPPED,
    Result,
    counts_toward_grade,
    days_failing,
    is_gated,
    letter_for,
    letter_from_pass_rate,
    neglect_cap,
    SCORE_BY_LETTER,
    reason_for,
    standard_letter,
    score_for,
    unverified_transition,
)

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ExecutionFacts:
    """The three facts of an execution row ``counts_toward_grade`` reads."""

    ref: str
    status: str
    error_origin: str = "standard"


def failing_for(days, status=FAILED, critical=False, name="Old", origin="standard"):
    """A not-passed result whose clock started ``days`` days ago."""
    return Result(
        status,
        level="critical" if critical else "high",
        error_origin=origin,
        name=name,
        first_failed_at=NOW - timedelta(days=days),
    )


def passed(critical=False, name="s"):
    return Result(PASSED, level="critical" if critical else "high", name=name)


def failed(critical=False, name="s"):
    return Result(FAILED, level="critical" if critical else "high", name=name)


def errored(critical=False, origin="standard", name="s"):
    return Result(ERROR, level="critical" if critical else "high", error_origin=origin, name=name)


class TestLetterFromPassRate(SimpleTestCase):
    def test_letter_from_pass_rate_bands(self):
        """A+ 100%, A >= 90, B >= 75, C >= 60, D below."""
        cases = [
            ((10, 10), "A+"),
            ((9, 10), "A"),
            ((8, 10), "B"),
            ((3, 4), "B"),
            ((7, 10), "C"),
            ((6, 10), "C"),
            ((5, 10), "D"),
            ((0, 1), "D"),
        ]
        for (ok, total), expected in cases:
            with self.subTest(passed=ok, total=total):
                self.assertEqual(letter_from_pass_rate(ok, total), expected)

    def test_a_pass_rate_needs_results(self):
        with self.assertRaises(ValueError):
            letter_from_pass_rate(0, 0)


class TestWhatCounts(SimpleTestCase):
    def test_running_rows_do_not_count(self):
        facts = ExecutionFacts(ref="", status=RUNNING)
        self.assertFalse(counts_toward_grade(facts, "main"))
        self.assertEqual(letter_for([Result(RUNNING)]).letter, NO_GRADE)

    def test_skipped_rows_are_ignored(self):
        facts = ExecutionFacts(ref="", status=SKIPPED)
        self.assertFalse(counts_toward_grade(facts, "main"))
        self.assertEqual(letter_for([Result(SKIPPED), passed()]).letter, "A+")

    def test_home_branch_runs_only(self):
        """A run that read the standard's home branch counts, whatever
        spelling its ref carries: bare, with the webhook's refs/heads/
        prefix, or empty when the home branch is the project's default (a
        manual run with no filter). Runs on any other branch never do."""
        cases = [
            ("refs/heads/main", True),
            ("main", True),
            ("", True),
            ("refs/heads/feature/x", False),
            ("develop", False),
            ("feature/x", False),
        ]
        for ref, expected in cases:
            with self.subTest(ref=ref):
                facts = ExecutionFacts(ref=ref, status=PASSED)
                self.assertIs(counts_toward_grade(facts, "main"), expected)

    def test_a_branch_scoped_standard_counts_on_its_own_branch(self):
        """A standard whose Branch/Tag Filter names ``develop`` grades on
        develop: runs there count, the default branch's and an empty ref
        (which reads the default branch) do not."""
        cases = [
            ("refs/heads/develop", True),
            ("develop", True),
            ("", False),
            ("main", False),
            ("refs/heads/main", False),
        ]
        for ref, expected in cases:
            with self.subTest(ref=ref):
                facts = ExecutionFacts(ref=ref, status=PASSED)
                self.assertIs(counts_toward_grade(facts, "develop", "main"), expected)

    def test_platform_errors_do_not_count(self):
        """GitGrit's own failure (stale sweep, job error, sandbox error)
        never moves the grade; the previous result stays."""
        facts = ExecutionFacts(ref="refs/heads/main", status=ERROR, error_origin=PLATFORM_ORIGIN)
        self.assertFalse(counts_toward_grade(facts, "main"))
        self.assertEqual(
            letter_for([passed(), errored(origin=PLATFORM_ORIGIN)]).letter, "A+"
        )

    def test_standard_origin_error_counts_as_not_passed(self):
        """An error inside the customer's own script is theirs to fix."""
        facts = ExecutionFacts(ref="", status=ERROR)
        self.assertTrue(counts_toward_grade(facts, "main"))
        grade = letter_for([passed()] * 9 + [errored()])
        self.assertEqual(grade.letter, "A")
        self.assertEqual(grade.reason, "1 standard failing")


class TestLetterFor(SimpleTestCase):
    def test_letter_from_pass_rate_of_the_standards_own_verdicts(self):
        self.assertEqual(letter_for([passed(), passed(), failed()]).letter, "C")
        self.assertEqual(letter_for([passed()] * 9 + [failed()]).letter, "A")

    def test_no_results_means_no_grade(self):
        grade = letter_for([])
        self.assertEqual(grade.letter, NO_GRADE)
        self.assertFalse(grade.graded)
        self.assertEqual(grade.reason, "no results yet")

    def test_reason_priority_failing_count_then_perfect(self):
        self.assertEqual(letter_for([passed(), passed()]).reason, "perfect")
        self.assertEqual(
            letter_for([passed(), failed()]).reason, "1 standard failing"
        )
        self.assertEqual(
            letter_for([passed(), failed(), errored()]).reason,
            "2 standards failing",
        )

    def test_a_neglect_cap_outranks_the_failing_count(self):
        results = [passed(), failed()]
        self.assertEqual(
            reason_for(results, "B", cap="failing for 15 days"), "failing for 15 days"
        )


class TestGate(SimpleTestCase):
    def test_any_critical_fail_is_an_f(self):
        results = [passed()] * 9 + [failed(critical=True, name="No secrets")]
        self.assertTrue(is_gated(results))
        grade = letter_for(results)
        self.assertEqual(grade.letter, "F")
        self.assertEqual(grade.reason, "No secrets failing")

    def test_critical_standard_origin_error_is_f_could_not_verify(self):
        results = [passed(), errored(critical=True, name="No secrets")]
        grade = letter_for(results)
        self.assertEqual(grade.letter, "F")
        self.assertEqual(grade.reason, "could not verify No secrets")

    def test_critical_platform_error_does_not_gate(self):
        results = [passed(), errored(critical=True, origin=PLATFORM_ORIGIN)]
        self.assertFalse(is_gated(results))
        self.assertEqual(letter_for(results).letter, "A+")

    def test_only_critical_all_passing_is_a_plus(self):
        grade = letter_for([passed(critical=True), passed(critical=True)])
        self.assertEqual(grade.letter, "A+")
        self.assertEqual(grade.reason, "perfect")

    def test_critical_reason_outranks_the_failing_count(self):
        results = [failed(), failed(), failed(critical=True, name="Gate")]
        self.assertEqual(letter_for(results).reason, "Gate failing")


class TestUnverifiedTransition(SimpleTestCase):
    def test_notifies_on_the_transition_only(self):
        current = errored(critical=True)
        self.assertTrue(unverified_transition(None, current))
        self.assertTrue(unverified_transition(passed(critical=True), current))
        self.assertTrue(unverified_transition(failed(critical=True), current))
        # A repeat error is silent.
        self.assertFalse(unverified_transition(errored(critical=True), current))

    def test_never_for_non_critical_failed_or_platform_errors(self):
        self.assertFalse(unverified_transition(None, errored(critical=False)))
        self.assertFalse(unverified_transition(None, failed(critical=True)))
        self.assertFalse(
            unverified_transition(None, errored(critical=True, origin=PLATFORM_ORIGIN))
        )


class TestNeglectCap(SimpleTestCase):
    def test_cap_b_after_14_days_and_c_after_30(self):
        self.assertEqual(neglect_cap(15), "B")
        self.assertEqual(neglect_cap(30), "B")
        self.assertEqual(neglect_cap(31), "C")
        self.assertEqual(neglect_cap(400), "C")
        # 9 of 10 passing is an A; one failing for 15 days caps it at B.
        grade = letter_for([passed()] * 9 + [failing_for(15)], now=NOW)
        self.assertEqual(grade.letter, "B")
        self.assertEqual(grade.reason, "Old failing for 15 days")
        self.assertEqual(
            letter_for([passed()] * 9 + [failing_for(40)], now=NOW).letter, "C"
        )

    def test_exactly_14_days_is_not_capped(self):
        """Strictly more than 14 days: day 14 itself is still an A."""
        self.assertIsNone(neglect_cap(14))
        self.assertIsNone(neglect_cap(0))
        self.assertEqual(
            days_failing(NOW - timedelta(days=14, hours=23), NOW), 14
        )
        grade = letter_for([passed()] * 9 + [failing_for(14)], now=NOW)
        self.assertEqual(grade.letter, "A")
        self.assertEqual(grade.reason, "1 standard failing")

    def test_a_standard_origin_error_keeps_the_clock_running(self):
        """Errored days are failing days (P10): a result that is now
        errored in its own run still carries the clock and is capped."""
        grade = letter_for([passed()] * 9 + [failing_for(17, status=ERROR)], now=NOW)
        self.assertEqual(grade.letter, "B")
        self.assertEqual(grade.reason, "Old failing for 17 days")

    def test_no_clock_means_no_cap(self):
        """A failing result without a clock (a commit's rows) is graded by
        pass rate alone."""
        self.assertEqual(letter_for([passed()] * 9 + [failed()], now=NOW).letter, "A")
        self.assertEqual(days_failing(None, NOW), 0)

    def test_critical_gate_outranks_the_cap_in_letter_and_reason(self):
        results = [failing_for(40, name="Old"), errored(critical=True, name="Gate")]
        grade = letter_for(results, now=NOW)
        self.assertEqual(grade.letter, "F")
        self.assertEqual(grade.reason, "could not verify Gate")

    def test_the_cap_never_raises_a_letter(self):
        """A D under a B cap stays a D, and the reason is the failing count
        because the cap is not what holds the letter down."""
        results = [passed(), failing_for(20, name="Old"), failed(), failed()]
        grade = letter_for(results, now=NOW)
        self.assertEqual(grade.letter, "D")
        self.assertEqual(grade.reason, "3 standards failing")
        # A C from the pass rate under a C cap: the cap binds and explains.
        results = [passed(), passed(), passed(), failing_for(40, name="Old"), failed()]
        grade = letter_for(results, now=NOW)
        self.assertEqual(grade.letter, "C")
        self.assertEqual(grade.reason, "Old failing for 40 days")

    def test_the_longest_failing_standard_names_the_reason(self):
        results = [passed()] * 9 + [failing_for(16, name="Newer"), failing_for(22, name="Older")]
        self.assertEqual(letter_for(results, now=NOW).reason, "Older failing for 22 days")


class ScoreForTests(SimpleTestCase):
    def test_every_letter_has_a_score_between_0_and_100_that_never_rises_as_the_letter_falls(self):
        scores = [score_for(letter) for letter in ("A+", "A", "B", "C", "D", "F")]
        assert all(0 <= s <= 100 for s in scores)
        assert scores == sorted(scores, reverse=True)
        assert score_for("A+") == 100 and score_for("F") == 0

    def test_no_grade_and_unknown_letters_have_no_score(self):
        assert score_for(NO_GRADE) is None
        assert score_for(None) is None
        assert score_for("Z") is None

    def test_the_table_covers_exactly_the_letters_a_grade_can_be(self):
        assert set(SCORE_BY_LETTER) == {"A+", "A", "B", "C", "D", "F"}


class TestStandardLetter(SimpleTestCase):
    def test_a_regular_standard_reads_its_score_through_the_pass_rate_bands(self):
        for score, letter in [(100, "A"), (90, "A"), (89, "B"), (75, "B"), (74, "C"), (60, "C"), (59, "D"), (0, "D")]:
            with self.subTest(score=score):
                status = PASSED if score >= 75 else FAILED
                self.assertEqual(standard_letter(score, status == PASSED, "high", status), letter)

    def test_a_critical_standard_is_a_when_passed_and_f_when_failed_or_errored(self):
        self.assertEqual(standard_letter(100, True, "critical", PASSED), "A")
        self.assertEqual(standard_letter(100, False, "critical", FAILED), "F")
        self.assertEqual(standard_letter(0, False, "critical", ERROR), "F")

    def test_a_critical_score_is_ignored(self):
        self.assertEqual(standard_letter(40, True, "critical", PASSED), "A")

    def test_running_skipped_errored_and_unscored_rows_have_no_letter(self):
        self.assertIsNone(standard_letter(0, False, "high", RUNNING))
        self.assertIsNone(standard_letter(0, False, "high", SKIPPED))
        self.assertIsNone(standard_letter(0, False, "high", ERROR))
        self.assertIsNone(standard_letter(None, True, "high", PASSED))
        self.assertIsNone(standard_letter(0, False, "critical", RUNNING))
