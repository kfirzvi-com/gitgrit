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
