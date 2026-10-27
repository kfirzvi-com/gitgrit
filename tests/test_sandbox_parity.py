"""The host and the sandbox must agree on how a standard is read.

The sandbox image cannot import the app, so "does evaluate() want ``llm``" is
decided twice: by AST in ``app/application/project_service.py`` and by
``inspect.signature`` in ``sandbox_image/entrypoint.py``. The same goes for the
shape of an error result. These tests run both sides on the same cases.
"""
from django.test import SimpleTestCase

from app.application.project_service import _evaluate_takes_llm
from app.infrastructure.sandbox.runner import error_result
from tests.test_sandbox_entrypoint import _load_entrypoint, _run_main

CASES = {
    "positional": ("def evaluate(project, llm):\n    return {}\n", True),
    "posonly": ("def evaluate(project, llm, /):\n    return {}\n", True),
    "keyword_only": ("def evaluate(project, *, llm):\n    return {}\n", True),
    "var_args": ("def evaluate(project, *args):\n    return {}\n", False),
    "var_kwargs": ("def evaluate(project, **kwargs):\n    return {}\n", False),
    "async_def": ("async def evaluate(project, llm):\n    return {}\n", True),
    "last_definition_wins": (
        "def evaluate(project, llm):\n    return {}\n\ndef evaluate(project):\n    return {}\n",
        False,
    ),
    "last_definition_wins_with_llm": (
        "def evaluate(project):\n    return {}\n\ndef evaluate(project, llm):\n    return {}\n",
        True,
    ),
    "posonly_then_llm": ("def evaluate(project, /, llm):\n    return {}\n", True),
    # The first parameter is the project, whatever its name.
    "first_param_named_llm": ("def evaluate(llm):\n    return {}\n", False),
    "first_param_named_llm_posonly": ("def evaluate(llm, /):\n    return {}\n", False),
    "log_only": ("def evaluate(project, log):\n    return {}\n", False),
    "no_llm": ("def evaluate(project):\n    return {}\n", False),
}



def _entrypoint_takes_llm(entrypoint, code):
    namespace = {}
    exec(code, namespace)
    return "llm" in entrypoint._injected_params(namespace["evaluate"])


class EvaluateTakesLlmParityTests(SimpleTestCase):
    def test_host_and_sandbox_agree(self):
        entrypoint = _load_entrypoint()
        for name, (code, expected) in CASES.items():
            with self.subTest(case=name):
                assert _evaluate_takes_llm(code) is expected
                assert _entrypoint_takes_llm(entrypoint, code) is expected


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
