"""The host and the sandbox must agree on the shape of an error result.

The sandbox image cannot import the app, so an error result is built twice:
by ``error_result`` in ``app/infrastructure/sandbox/runner.py`` and by
``sandbox_image/entrypoint.py``. This test runs both sides.
"""
from django.test import SimpleTestCase

from app.infrastructure.sandbox.runner import error_result
from tests.test_sandbox_entrypoint import _load_entrypoint, _run_main


class ErrorResultParityTests(SimpleTestCase):
    def test_entrypoint_exception_result_matches_error_result(self):
        sandbox_result = _run_main(
            _load_entrypoint(), "def evaluate(project):\n    raise ValueError('boom')\n"
        )
        sandbox_result.pop("logs", None)  # added to every result, not part of the shape

        host_result = error_result("x")
        assert sandbox_result.keys() == host_result.keys()
        for key in host_result:
            assert type(sandbox_result[key]) is type(host_result[key]), key
        assert sandbox_result["details"] == host_result["details"]
