"""``eval_topology --runs N``, repeated ``--fixture`` and ``--jev on``:
multi-run scoring helpers and the summary block.

The pure helpers (``f1``, ``jaccard_distance``, ``summarize``, ``flip_rate``)
are tested without Django. The command itself runs against a ``--fixture``
that equals the golden, so every run scores 1.0 and nothing flips; that pins
the plumbing (per-run tables, summary, ``-run<N>`` save files) without a model.
"""
from __future__ import annotations

import importlib.util
import json
import re
import unittest
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from model_bakery import baker

from app.management.commands.eval_topology import (
    edge_keys,
    f1,
    flip_rate,
    jaccard_distance,
    run_output_path,
    summarize,
)
from tests.jev_support import FakeJevClient, link_answers, use_jev
from tests.support import MonkeyPatchMixin, TmpPathMixin

GOLDEN = {
    "components": [
        {"path": "apps/web", "name": "web", "kind": "frontend"},
        {"path": "services/auth", "name": "auth-service", "kind": "service"},
    ],
    "internal": [{"source_path": "apps/web", "target_ref": "{repo}#services/auth", "label": "REST"}],
    "externals": [{"source_path": "services/auth", "name": "Stripe"}],
    "infrastructure": [{"source_path": "services/auth", "name": "users db", "kind": "database"}],
    "evidence": {"files_read": ["README.md"]},
}


def _row(section, precision, recall):
    return {"section": section, "precision": precision, "recall": recall}


def _rows(precision=1.0, recall=1.0):
    return [_row(s, precision, recall) for s in ("components", "internal", "externals", "infrastructure")]


class TestF1(unittest.TestCase):
    def test_perfect(self):
        self.assertEqual(f1(1.0, 1.0), 1.0)

    def test_harmonic_mean(self):
        self.assertAlmostEqual(f1(0.5, 1.0), 2 / 3)

    def test_both_zero_is_zero_not_division_error(self):
        self.assertEqual(f1(0.0, 0.0), 0.0)


class TestJaccardDistance(unittest.TestCase):
    def test_identical_sets(self):
        self.assertEqual(jaccard_distance({1, 2}, {1, 2}), 0.0)

    def test_disjoint_sets(self):
        self.assertEqual(jaccard_distance({1}, {2}), 1.0)

    def test_partial_overlap(self):
        self.assertAlmostEqual(jaccard_distance({1, 2, 3}, {2, 3, 4}), 0.5)

    def test_both_empty(self):
        self.assertEqual(jaccard_distance(set(), set()), 0.0)


class TestFlipRate(unittest.TestCase):
    def test_single_run_is_zero(self):
        self.assertEqual(flip_rate([{1, 2}]), 0.0)

    def test_mean_of_consecutive_distances(self):
        # 1→2 identical (0), 2→3 disjoint (1) → mean 0.5
        self.assertAlmostEqual(flip_rate([{1}, {1}, {2}]), 0.5)

    def test_edge_keys_join_internal_and_externals_only(self):
        keys = {
            "components": {"apps/web"},
            "internal": {("apps/web", "org/repo#services/auth")},
            "externals": {("services/auth", "stripe", "outbound")},
            "infrastructure": {("services/auth", "database")},
        }
        self.assertEqual(
            edge_keys(keys),
            {
                ("internal", "apps/web", "org/repo#services/auth"),
                ("externals", "services/auth", "stripe", "outbound"),
            },
        )


class TestSummarize(unittest.TestCase):
    def test_means_over_runs(self):
        summary = summarize([_rows(1.0, 1.0), _rows(0.5, 1.0)])
        internal = summary["internal"]
        self.assertAlmostEqual(internal["precision"], 0.75)
        self.assertAlmostEqual(internal["recall"], 1.0)
        # F1 is per run then averaged: (1.0 + 2/3) / 2
        self.assertAlmostEqual(internal["f1"], (1.0 + 2 / 3) / 2)

    def test_all_zero_run(self):
        summary = summarize([_rows(0.0, 0.0)])
        self.assertEqual(summary["externals"], {"precision": 0.0, "recall": 0.0, "f1": 0.0})

    def test_every_section_present(self):
        self.assertEqual(
            tuple(summarize([_rows()])), ("components", "internal", "externals", "infrastructure")
        )


class TestRunOutputPath(unittest.TestCase):
    def test_single_run_keeps_name(self):
        self.assertEqual(str(run_output_path("out.json", 1, 1)), "out.json")

    def test_multi_run_adds_suffix(self):
        self.assertEqual(str(run_output_path("dir/out.json", 2, 3)), "dir/out-run2.json")


class _EvalTopologyTestCase(MonkeyPatchMixin, TmpPathMixin, TestCase):
    def setUp(self):
        super().setUp()
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        self.project = baker.make(
            "app.Project", tenant=tenant, platform_connection=conn, name="repo", full_path="org/repo"
        )
        self.repo = self.tmp_path / "repo"
        self.repo.mkdir()
        (self.repo / "README.md").write_text("# repo\n")
        (self.repo / "package.json").write_text('{"name": "repo"}\n')
        self.golden = self.tmp_path / "golden.json"
        self.golden.write_text(json.dumps(GOLDEN))

    def run_command(self, *extra):
        out = StringIO()
        call_command(
            "eval_topology",
            str(self.project.id),
            "--local-path",
            str(self.repo),
            "--golden",
            str(self.golden),
            "--fixture",
            str(self.golden),
            *extra,
            stdout=out,
            stderr=StringIO(),
        )
        return out.getvalue()


class TestEvalTopologyRuns(_EvalTopologyTestCase):
    def test_two_fixtures_are_two_runs_and_the_flip_rate_is_their_disagreement(self):
        # The second fixture lacks the internal edge: run 1 has 2 edges, run 2 has 1
        # in common → Jaccard distance 0.5 between the two "drafts".
        other = self.tmp_path / "draft2.json"
        other.write_text(json.dumps({**GOLDEN, "internal": []}))
        save = self.tmp_path / "out.json"
        text = self.run_command("--fixture", str(other), "--save-json", str(save))

        self.assertIn("=== run 1/2 (fixture golden.json) ===", text)
        self.assertIn("=== run 2/2 (fixture draft2.json) ===", text)
        self.assertNotIn("=== run 1/2 ===", text)
        self.assertIn("=== summary over 2 runs ===", text)
        self.assertIn(f"{'internal':<15}{0.5:>7.2f}{0.5:>7.2f}{0.5:>7.2f}", text)  # run 1 perfect, run 2 empty
        self.assertIn("flip rate (internal ∪ externals): 0.50", text)
        self.assertEqual(len(json.loads((self.tmp_path / "out-run1.json").read_text())["internal"]), 1)
        self.assertEqual(len(json.loads((self.tmp_path / "out-run2.json").read_text())["internal"]), 0)

    def test_runs_above_one_with_several_fixtures_is_an_error(self):
        from django.core.management.base import CommandError

        with self.assertRaisesRegex(CommandError, "each fixture is one run"):
            self.run_command("--fixture", str(self.golden), "--runs", "2")
        self.run_command("--fixture", str(self.golden), "--runs", "1")  # explicit 1 is fine

    def test_two_runs_score_perfect_and_never_flip(self):
        save = self.tmp_path / "out.json"
        text = self.run_command("--runs", "2", "--save-json", str(save))

        self.assertIn("=== run 1/2 ===", text)
        self.assertIn("=== run 2/2 ===", text)
        self.assertIn("=== summary over 2 runs ===", text)
        for section in ("components", "internal", "externals", "infrastructure"):
            self.assertIn(f"{section:<15}{1.0:>7.2f}{1.0:>7.2f}{1.0:>7.2f}", text)
        self.assertIn("flip rate (internal ∪ externals): 0.00", text)
        self.assertNotIn("jev:", text)  # off by default

        self.assertFalse(save.exists())
        for n in (1, 2):
            path = self.tmp_path / f"out-run{n}.json"
            self.assertTrue(path.exists(), path)
            self.assertEqual(len(json.loads(path.read_text())["components"]), 2)

    def test_single_run_keeps_plain_save_path(self):
        save = self.tmp_path / "out.json"
        text = self.run_command("--save-json", str(save))
        self.assertTrue(save.exists())
        self.assertIn("=== summary over 1 run ===", text)
        self.assertNotIn("=== run 1/1 ===", text)

    def test_replay_without_jev_on_is_an_error(self):
        from django.core.management.base import CommandError

        with self.assertRaisesRegex(CommandError, "need --jev on"):
            self.run_command("--replay-jev", str(self.tmp_path / "c.json"))

    def test_jev_on_without_key_or_replay_is_a_clear_error(self):
        if importlib.util.find_spec("app.infrastructure.topology.jev_links") is None:
            self.skipTest("jev_links not landed yet")  # the link stage is imported before the client
        from django.core.management.base import CommandError

        use_jev(self.monkeypatch, None)
        with self.assertRaisesRegex(CommandError, "Jev is not configured"):
            self.run_command("--jev", "on")


class TestEvalTopologyJev(_EvalTopologyTestCase):
    """``--jev on --replay-jev``: the fixture inference wrapped in
    ``LinkEnrichedInference`` with a cassette-backed Jev.

    The cassette is empty, so every candidate the scanner asks about is
    answered with a ``JevError`` (unknown state) and lands in the ``failed``
    band; the wrapper then returns the inner topology unchanged and scores
    stay 1.0.
    What this pins is the wiring: the command runs end to end with no key and
    no network, and prints the Jev usage block.
    """

    def setUp(self):
        if importlib.util.find_spec("app.infrastructure.topology.jev_links") is None:
            self.skipTest("jev_links not landed yet")
        super().setUp()
        # Candidates for the link scanner: one env var pointing at a sibling the
        # golden already links (skipped as covered) and one pointing at another
        # workspace repository that is not on the map (asked).
        baker.make(
            "app.Project",
            tenant=self.project.tenant,
            platform_connection=self.project.platform_connection,
            name="orders",
            full_path="org/orders",
        )
        # Inside a component: a root-level file belongs to nobody when the
        # golden has no root component, so the scanner would skip it.
        (self.repo / "apps" / "web").mkdir(parents=True, exist_ok=True)
        (self.repo / "apps" / "web" / ".env.example").write_text(
            "AUTH_SERVICE_URL=http://auth-service:8000\nORDERS_SERVICE_URL=http://orders:8000\n"
        )
        self.cassette = self.tmp_path / "cassette.json"
        self.cassette.write_text("{}")

    def test_replay_run_prints_jev_block_and_keeps_scores(self):
        text = self.run_command("--jev", "on", "--replay-jev", str(self.cassette), "--runs", "2")

        self.assertIn("=== summary over 2 runs ===", text)
        self.assertIn(f"{'internal':<15}{1.0:>7.2f}{1.0:>7.2f}{1.0:>7.2f}", text)
        self.assertIn("flip rate (internal ∪ externals): 0.00", text)
        usage = re.search(r"jev: (\d+) calls, (\d+) input tokens, (\d+) failures", text)
        calls, tokens, failures = map(int, usage.groups())
        self.assertGreaterEqual(calls, 2)  # the env var candidate, once per run
        self.assertEqual(failures, calls)  # an empty cassette answers nothing
        self.assertEqual(tokens, 0)
        failed = int(re.search(r"jev decisions: .*failed (\d+)", text).group(1))
        self.assertGreaterEqual(failed, 2)
        self.assertEqual(failed, calls)
        # Jev answered nothing, so no LLM edge was judged either way.
        self.assertIn("jev verdicts: kept 0, moved 0, removed 0, no_evidence 0", text)

    def test_verdicts_on_the_fixtures_own_edges_are_counted_across_fixtures(self):
        # Jev confirms both env vars: the golden's web→auth edge is covered and kept, the
        # orders edge is added (an extra), and the Stripe external has no evidence in the
        # checkout and is removed. Two fixtures → the verdicts are summed over both runs.
        use_jev(self.monkeypatch, FakeJevClient(link_answers()))
        other = self.tmp_path / "draft2.json"
        other.write_text(json.dumps(GOLDEN))

        text = self.run_command("--fixture", str(other), "--jev", "on")

        self.assertIn("=== run 2/2 (fixture draft2.json) ===", text)
        self.assertIn("jev verdicts: kept 2, moved 0, removed 0, no_evidence 2", text)
        self.assertRegex(text, r"jev decisions: confirmed 4, unsure 0, dropped 0, failed 0")
        self.assertIn("internal extra: ('apps/web', 'org/orders')", text)
        self.assertIn("externals missed: ('services/auth', 'stripe', 'outbound')", text)
        self.assertIn("flip rate (internal ∪ externals): 0.00", text)

    def test_record_and_replay_together_is_an_error(self):
        from django.core.management.base import CommandError

        with self.assertRaisesRegex(CommandError, "exclusive"):
            self.run_command(
                "--jev", "on", "--record-jev", str(self.tmp_path / "a.json"), "--replay-jev", str(self.cassette)
            )

    def test_zero_runs_is_an_error(self):
        from django.core.management.base import CommandError

        with self.assertRaisesRegex(CommandError, "at least 1"):
            self.run_command("--runs", "0")

    def test_record_jev_wraps_the_client_in_a_recorder(self):
        from app.infrastructure.jev import RecordingJevClient

        fake = use_jev(self.monkeypatch, FakeJevClient(link_answers("none", p=0.9, runtime=0.1, inactive=0.1)))
        wrapped: list = []
        original = RecordingJevClient.__init__

        def spy(self_, inner, cassette_path):
            wrapped.append(inner)
            original(self_, inner, cassette_path)

        self.monkeypatch.setattr(RecordingJevClient, "__init__", spy)
        cassette = self.tmp_path / "recorded.json"

        text = self.run_command("--jev", "on", "--record-jev", str(cassette))

        self.assertEqual(wrapped, [fake])
        self.assertGreaterEqual(len(fake.calls), 1)
        self.assertEqual(len(json.loads(cassette.read_text())), len(fake.calls))
        self.assertRegex(text, r"jev decisions: .*dropped [1-9]")
