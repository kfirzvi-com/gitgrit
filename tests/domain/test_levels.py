"""The standard level rules (``app.domain.levels``): one test per rule."""
from django.test import SimpleTestCase

from app.domain import levels
from app.domain.grading import ERROR, FAILED, PASSED, Result, letter_for
from app.domain.levels import StandardLevel


class TestLevelRules(SimpleTestCase):
    def test_default_is_high(self):
        assert levels.DEFAULT_LEVEL is StandardLevel.HIGH
        assert set(StandardLevel) == {StandardLevel.HIGH, StandardLevel.CRITICAL}
        assert Result(PASSED).level == "high"

    def test_critical_and_high_behavior(self):
        critical = levels.rule_for("critical")
        high = levels.rule_for("high")
        for field in (
            "gates_grade", "pass_or_fail_letter", "alerts_when_unverified", "shown_as_critical"
        ):
            with self.subTest(field=field):
                assert getattr(critical, field) is True
                assert getattr(high, field) is False
        assert critical.in_pass_rate is False
        assert high.in_pass_rate is True

    def test_an_unknown_level_is_logged_and_an_empty_one_is_not(self):
        with self.assertLogs("app.domain.levels", "WARNING") as logs:
            levels.rule_for("blocker")
        assert "blocker" in logs.output[0]
        with self.assertNoLogs("app.domain.levels", "WARNING"):
            levels.rule_for("")
            levels.rule_for(None)

    def test_unknown_or_empty_level_reads_as_the_default(self):
        for value in ("blocker", "", None):
            with self.subTest(value=value):
                assert levels.rule_for(value) is levels.LEVEL_RULES[StandardLevel.HIGH]
                assert levels.rule_for(value).gates_grade is False

    def test_every_level_has_exactly_one_rule(self):
        assert set(levels.LEVEL_RULES) == set(StandardLevel)
        for level, rule in levels.LEVEL_RULES.items():
            assert rule.level is level
            assert len(level.value) <= levels.MAX_LENGTH

    def test_choices_come_from_the_rules_most_severe_first(self):
        assert levels.level_choices() == [("critical", "Critical"), ("high", "High")]

    def test_parse_level_accepts_any_case_and_rejects_unknown(self):
        assert levels.parse_level(" Critical ") is StandardLevel.CRITICAL
        assert levels.parse_level("high") is StandardLevel.HIGH
        for value in ("blocker", "", None):
            with self.subTest(value=value):
                with self.assertRaises(levels.UnknownLevel):
                    levels.parse_level(value)


class TestTheGradeAsksTheRule(SimpleTestCase):
    def test_a_failing_critical_result_is_an_f_and_a_failing_high_is_not(self):
        assert letter_for([Result(PASSED), Result(FAILED, level="critical")]).letter == "F"
        assert letter_for([Result(PASSED), Result(FAILED, level="high")]).letter != "F"

    def test_an_unverified_critical_result_is_an_f(self):
        assert letter_for([Result(ERROR, level="critical", name="Gate")]).letter == "F"
