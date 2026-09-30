"""``infer_and_store`` picks the Jev link stage up when Jev is configured.

Same stubbing as ``test_dependency_agent`` (``make_workspace``): the LLM role
and agent are stubbed, the platform client is an in-memory tree.
``use_jev`` patches ``JevClient.from_settings`` to hand back a
``FakeJevClient`` (Jev on) or ``None`` (Jev off); that is the whole switch,
so the test does not depend on env vars.
"""
from __future__ import annotations

import json

from django.test import TestCase

from app.application import dependency_agent as da
from app.domain.models import ComponentDependency
from app.infrastructure.topology import llm_inference as li
from app.infrastructure.topology.jev_links import LinkEnrichedInference
from tests.application.dependency_agent_support import fake_client, make_workspace
from tests.jev_support import FakeJevClient, JevError, link_answers, use_jev
from tests.support import MonkeyPatchMixin

TREE = ("README.md", "package.json", ".env.example")
FILES = {
    "README.md": "# web\n",
    "package.json": '{"name": "web"}',
    ".env.example": "ORDERS_SERVICE_URL=http://orders:8000\n",
}
REFRESH_LOGGER = "app.application.architecture.refresh"


class DependencyAgentJevTests(MonkeyPatchMixin, TestCase):
    def setUp(self):
        super().setUp()
        # The LLM lists the tree, reads package.json and returns no edges.
        _tenant, self.web, self.orders = make_workspace(
            self.monkeypatch,
            client=fake_client(TREE, FILES),
            sibling=("orders", "org/orders"),
            deps=li.DependencyResult(technologies=["Express"]),
        )

    def test_jev_on_adds_a_confirmed_link_as_a_component_dependency(self):
        jev = use_jev(self.monkeypatch, FakeJevClient(link_answers()))

        with self.assertLogs(REFRESH_LOGGER, level="INFO") as logs:
            summary = da.infer_and_store(self.web)

        self.assertEqual(len(jev.calls), 1)
        self.assertEqual(jev.calls[0][0]["reference"], "ORDERS_SERVICE_URL")
        self.assertEqual(jev.calls[0][0]["candidates"]["A"]["ref"], "org/orders")
        dep = ComponentDependency.objects.get(source=self.web.root_component)
        self.assertEqual(dep.target, self.orders.root_component)
        self.assertEqual(dep.label, "runtime")
        self.assertEqual(summary.internal, 1)
        self.web.refresh_from_db()
        self.assertEqual(self.web.deps_evidence[0], "package.json")  # the LLM's own read comes first
        self.assertIn(".env.example", self.web.deps_evidence)
        # One audit line per decision goes through the refresh logger, without the snippet.
        prefix = "deps[web]: jev-link "
        lines = [r.getMessage() for r in logs.records if r.getMessage().startswith(prefix)]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0][len(prefix):])
        self.assertEqual(entry["band"], "confirmed")
        self.assertNotIn("code", entry)

    def test_jev_off_runs_the_plain_llm_inference(self):
        use_jev(self.monkeypatch, None)

        da.infer_and_store(self.web)

        self.assertEqual(ComponentDependency.objects.filter(source__project=self.web).count(), 0)

    def test_default_inference_is_wrapped_iff_a_client_is_configured(self):
        captured = {}

        class Capture:
            def __init__(self, *, inference, snapshot_factory, enqueue_refresh=None):
                captured["inference"] = inference

            def run(self, project):
                return None

        self.monkeypatch.setattr(da, "RefreshProjectTopology", Capture)

        use_jev(self.monkeypatch, FakeJevClient(link_answers()))
        da.infer_and_store(self.web)
        self.assertIsInstance(captured["inference"], LinkEnrichedInference)

        use_jev(self.monkeypatch, None)
        da.infer_and_store(self.web)
        self.assertIsInstance(captured["inference"], li.LLMTopologyInference)

    def test_jev_down_keeps_the_llm_result(self):
        use_jev(self.monkeypatch, FakeJevClient(raise_on=JevError("down")))

        summary = da.infer_and_store(self.web)

        self.assertEqual(summary.internal, 0)
        self.web.refresh_from_db()
        self.assertEqual(self.web.deps_evidence, ["package.json"])
