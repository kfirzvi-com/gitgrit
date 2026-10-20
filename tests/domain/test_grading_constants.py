"""The grade rules keep their own copies of values stored or shown elsewhere
(execution statuses, error origins, the health tones the front end paints).
These tests are the only thing that makes the copies drift loudly."""
import re
from pathlib import Path

from django.test import SimpleTestCase

from app.domain import grading
from app.domain.models import StandardExecution
from app.infrastructure.sandbox import runner

STATIC = Path(__file__).resolve().parents[2] / "app" / "static" / "app"
TONES = {grading.TONE_GOOD, grading.TONE_ATTENTION, grading.TONE_FAILING, grading.TONE_UNKNOWN}


class GradingConstantParityTests(SimpleTestCase):
    def test_statuses_match_the_execution_model(self):
        Status = StandardExecution.Status
        assert grading.RUNNING == Status.RUNNING
        assert grading.PASSED == Status.PASSED
        assert grading.FAILED == Status.FAILED
        assert grading.ERROR == Status.ERROR
        assert grading.SKIPPED == Status.SKIPPED

    def test_error_origins_match_the_model_and_the_runner(self):
        Origin = StandardExecution.ErrorOrigin
        assert grading.STANDARD_ORIGIN == Origin.STANDARD
        assert grading.PLATFORM_ORIGIN == Origin.PLATFORM
        assert runner.PLATFORM_ERROR_ORIGIN == Origin.PLATFORM

    def test_tone_names_match_the_front_end_health_levels(self):
        source = (STATIC / "flow-common.js").read_text()
        body = re.search(r"HEALTH_LEVELS\s*=\s*\[([^\]]*)\]", source).group(1)
        assert set(re.findall(r"[\"']([a-z]+)[\"']", body)) == TONES

    def test_tone_names_match_the_css_health_selectors(self):
        source = (STATIC / "architecture.css").read_text()
        assert set(re.findall(r"\.gg-health-([a-z]+)\s*\{", source)) == TONES
