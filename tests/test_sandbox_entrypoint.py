"""Unit tests for the sandbox entrypoint's run log (sandbox_image/entrypoint.py).

The entrypoint reads /standard.py and /input.json; we swap the module's ``open``
for one that serves those two paths from memory and use the mock provider, so no
container or network is involved. stdout is captured because ``main()`` prints
the JSON result there.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

from django.test import SimpleTestCase

SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox_image"


def _load_entrypoint():
    if str(SANDBOX_DIR) not in sys.path:
        sys.path.insert(0, str(SANDBOX_DIR))
    import entrypoint  # noqa: WPS433

    return entrypoint


def _run_main(entrypoint, standard_code, config=None):
    files = {
        "/standard.py": standard_code,
        "/input.json": json.dumps(config or {"platform": "mock", "project_id": "p1"}),
    }
    real_open = open

    def fake_open(path, *args, **kwargs):
        if path in files:
            return io.StringIO(files[path])
        return real_open(path, *args, **kwargs)

    entrypoint.open = fake_open
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            entrypoint.main()
    finally:
        del entrypoint.open
    return json.loads(out.getvalue())


class SandboxEntrypointLogTests(SimpleTestCase):
    def setUp(self):
        self.entrypoint = _load_entrypoint()

    def test_standard_without_log_calls_gets_runtime_entries(self):
        result = _run_main(
            self.entrypoint,
            "def evaluate(project):\n"
            "    return {'passed': True, 'score': 100, 'message': 'all good'}\n",
        )

        self.assertTrue(result["passed"])
        messages = [e["message"] for e in result["logs"]]
        self.assertEqual(messages[0], "run started: platform=mock project=p1")
        self.assertEqual(messages[1], "project context ready")
        self.assertEqual(messages[2], "calling evaluate(project)")
        self.assertTrue(messages[3].startswith("evaluate returned passed=True score=100 message='all good' in "))
        self.assertEqual(messages[-1], "run finished: passed")
        self.assertTrue(all(e["level"] == "info" for e in result["logs"]))
        self.assertEqual(set(result["logs"][0]), {"level", "message", "ts"})

    def test_author_log_entries_are_interleaved(self):
        result = _run_main(
            self.entrypoint,
            "def evaluate(project, log):\n"
            "    log('checking README')\n"
            "    return {'passed': False, 'score': 0, 'message': 'missing'}\n",
        )

        messages = [e["message"] for e in result["logs"]]
        self.assertEqual(messages[2], "calling evaluate(project, log)")
        self.assertEqual(messages[3], "checking README")
        self.assertEqual(messages[-1], "run finished: failed")

    def test_raising_standard_logs_traceback_as_error(self):
        result = _run_main(
            self.entrypoint,
            "def evaluate(project):\n    raise ValueError('boom')\n",
        )

        self.assertFalse(result["passed"])
        self.assertTrue(result["details"]["error"])
        errors = [e for e in result["logs"] if e["level"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("ValueError: boom", errors[0]["message"])
        self.assertIn("Traceback", errors[0]["message"])
        self.assertEqual(result["logs"][-1]["message"], "run finished: error")
