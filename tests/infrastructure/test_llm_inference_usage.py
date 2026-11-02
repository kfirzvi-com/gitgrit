"""The map build's token usage travels out of the inference on its evidence."""
from django.test import SimpleTestCase

from app.application.architecture.ports import InferenceContext
from app.infrastructure.topology.llm_inference import (
    ComponentDiscovery,
    DependencyResult,
    LLMTopologyInference,
)

USAGE = {"prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000, "calls": 2}


class _Snapshot:
    def list_files(self):
        return ["README.md", "package.json"]

    def read_file(self, path):
        return "x"


class _Agent:
    """Answers both prompts with a root-only repository and reports ``USAGE``."""

    def __init__(self, log):
        self.usage = dict(USAGE)

    def run(self, *, toolbox, system_prompt, instructions, response_model):
        if response_model is ComponentDiscovery:
            return ComponentDiscovery(components=[{"path": "", "name": "mono"}])
        return DependencyResult()


class LLMInferenceUsageTests(SimpleTestCase):
    def test_tokens_spent_by_the_agent_land_on_the_evidence(self):
        inference = LLMTopologyInference({"model": "m"}, agent_factory=_Agent)
        topology = inference.infer(_Snapshot(), InferenceContext(project_name="mono", full_path="org/mono"))
        self.assertEqual(topology.evidence.llm_usage, USAGE)
