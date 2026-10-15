"""When something is worth a notification."""
from unittest import TestCase

from app.domain.events import DependencyInferenceFailed, StandardRunFinished
from app.domain.notifications import notification_rules as rules


def _run(passed=0, failed=0, errored=0, error=""):
    return StandardRunFinished(
        project_id="p", tenant_id="t", execution_ids=(),
        passed=passed, failed=failed, errored=errored, error=error,
    )


class RunRulesTests(TestCase):
    def test_a_job_error_could_not_be_evaluated(self):
        self.assertTrue(rules.could_not_evaluate(_run(passed=3, error="401 Bad credentials")))

    def test_every_standard_errored_could_not_be_evaluated(self):
        self.assertTrue(rules.could_not_evaluate(_run(errored=2)))

    def test_some_errors_among_results_could_be_evaluated(self):
        self.assertFalse(rules.could_not_evaluate(_run(passed=1, errored=1)))
        self.assertFalse(rules.could_not_evaluate(_run(failed=1, errored=1)))

    def test_standards_failing_needs_failures(self):
        self.assertTrue(rules.standards_failing(_run(passed=1, failed=2)))
        self.assertFalse(rules.standards_failing(_run(passed=3)))

    def test_could_not_evaluate_outranks_standards_failing(self):
        self.assertFalse(rules.standards_failing(_run(failed=2, error="boom")))


class GraphRuleTests(TestCase):
    def _event(self, had_worked_before):
        return DependencyInferenceFailed(
            project_id="p", tenant_id="t", error="x", had_worked_before=had_worked_before
        )

    def test_only_a_map_that_used_to_build_is_worth_telling(self):
        self.assertTrue(rules.graph_broke(self._event(True)))
        self.assertFalse(rules.graph_broke(self._event(False)))
def _map_failure(error="boom", status=None, had_worked_before=True):
    return DependencyInferenceFailed(
        project_id="p", tenant_id="t", error=error,
        had_worked_before=had_worked_before, provider_status=status,
    )


class TurnedCriticalTests(TestCase):
    """``turned_critical`` reads letters: the grade dropped to F."""

    def test_any_graded_letter_to_f_is_a_drop(self):
        for before in ("A+", "A", "B", "C", "D"):
            with self.subTest(before=before):
                self.assertTrue(rules.turned_critical(before, "F"))

    def test_already_f_or_no_grade_did_not_drop(self):
        self.assertFalse(rules.turned_critical("F", "F"))
        self.assertFalse(rules.turned_critical("—", "F"))
        self.assertFalse(rules.turned_critical(None, "F"))

    def test_staying_above_f_is_not_a_drop(self):
        self.assertFalse(rules.turned_critical("A", "D"))
        self.assertFalse(rules.turned_critical("F", "A"))


class AIProviderTests(TestCase):
    def test_refusal_statuses(self):
        for status in (401, 402, 403):
            with self.subTest(status=status):
                self.assertTrue(rules.ai_provider_refused(_map_failure(status=status)))

    def test_refusal_text_without_a_status(self):
        error = 'AnthropicException - "Your credit balance is too low to access the Anthropic API."'
        self.assertTrue(rules.ai_provider_refused(_map_failure(error=error)))

    def test_other_failures_are_not_the_provider(self):
        self.assertFalse(rules.ai_provider_refused(_map_failure(error="timed out", status=500)))

    def test_a_provider_refusal_is_not_a_broken_graph(self):
        self.assertFalse(rules.graph_broke(_map_failure(status=401)))
        self.assertTrue(rules.graph_broke(_map_failure(error="timed out")))


class AuthFailureTests(TestCase):
    def test_platform_refusals_look_like_auth_failures(self):
        for error in ("401 Bad credentials", "HTTPError: 403 Forbidden", "Unauthorized"):
            with self.subTest(error=error):
                self.assertTrue(rules.looks_like_auth_failure(error))

    def test_other_errors_do_not(self):
        self.assertFalse(rules.looks_like_auth_failure("sandbox exploded"))
        self.assertFalse(rules.looks_like_auth_failure(""))
