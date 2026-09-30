"""``eval_jev_links`` scores a labelled case file against a (fake) Jev.

Four cases — a roster target, an external, a ``none`` and a labelled kind —
answered by a ``FakeJevClient`` keyed on the reference, so the expected
accuracy, confusion and PASS/FAIL lines are known exactly. Every run passes
``--confirm 0.60 --unsure 0.25`` itself, so the numbers below do not move if
the production defaults are retuned.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from app.domain.architecture.links import LinkCandidate, TargetOption
from app.infrastructure.jev import client_for
from app.infrastructure.topology.jev_links import build_state, component_for
from app.management.commands.eval_jev_links import load_cases
from tests.jev_support import FakeJevClient, link_answers, use_jev
from tests.support import MonkeyPatchMixin, TmpPathMixin

AUTH = "org/mono#services/auth-service"


def candidate(reference, kind="env_var", options=(), external_name="", source_path="apps/api-gateway"):
    return LinkCandidate(
        source_path=source_path,
        file=f"{source_path}/src/config.ts",
        line=3,
        code=f"x = process.env.{reference}",
        reference=reference,
        reference_kind=kind,
        options=tuple(
            TargetOption(chr(65 + i), ref, ref.rsplit("/", 1)[-1], "service") for i, ref in enumerate(options)
        ),
        external_name=external_name,
    )


CASES = [
    (candidate("AUTH_SERVICE_URL", options=(AUTH, "org/auth-service")), AUTH, "runtime"),
    (candidate("api.stripe.com", kind="url", external_name="stripe"), "external:stripe", ""),
    (candidate("DATA_URL", options=(AUTH,)), "none", ""),
    (candidate("MOCK_AUTH_URL", options=(AUTH,)), AUTH, "test"),
    (candidate("UNLABELLED_URL", options=(AUTH,)), "", ""),  # skipped
]


def perfect(state, questions):
    return {
        "AUTH_SERVICE_URL": link_answers("A"),
        "api.stripe.com": link_answers("external"),
        "DATA_URL": link_answers("none"),
        "MOCK_AUTH_URL": link_answers("A", kind="test"),
    }[state["reference"]]


def one_wrong(state, questions):
    if state["reference"] == "DATA_URL":
        return link_answers("A")  # an edge to auth where none exists
    return perfect(state, questions)


def curve_rows(text: str) -> list[list[str]]:
    """The precision/recall table as whitespace-split rows, first token the threshold."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('precision/recall of "add edge":'))
    rows = []
    for line in lines[start + 2:]:  # skip the header row
        if not line.strip():
            break
        rows.append(line.split())
    return rows


def row_at(text: str, threshold: str) -> list[str]:
    return next(row for row in curve_rows(text) if row[0] == threshold)


class EvalJevLinksTests(MonkeyPatchMixin, TmpPathMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.cases = self.tmp_path / "cases.jsonl"
        with open(self.cases, "w", encoding="utf-8") as fh:
            for c, target, kind in CASES:
                fh.write(json.dumps({**asdict(c), "expected_target": target, "expected_kind": kind}) + "\n")

    def use(self, answers) -> FakeJevClient:
        return use_jev(self.monkeypatch, FakeJevClient(answers))

    def run_command(self, *extra, confirm="0.60", unsure="0.25"):
        out = StringIO()
        call_command(
            "eval_jev_links", "--cases", str(self.cases), "--confirm", confirm, "--unsure", unsure, *extra,
            stdout=out, stderr=StringIO(),
        )
        return out.getvalue()

    def test_load_cases_skips_unlabelled_lines_and_rebuilds_candidates(self):
        cases = load_cases(self.cases)
        self.assertEqual(len(cases), 4)
        self.assertEqual(cases[0]["candidate"], CASES[0][0])
        self.assertEqual(cases[0]["candidate"].options[0], TargetOption("A", AUTH, "auth-service", "service"))

    def test_perfect_answers_pass(self):
        jev = self.use(perfect)
        text = self.run_command("--runs", "2")

        self.assertEqual(len(jev.calls), 8)
        self.assertIn("cases: 4 (roster 2, external 1, none 1), runs: 2", text)
        self.assertIn("target accuracy: 1.00 (8/8)", text)
        self.assertIn("edge_kind accuracy: 1.00 (4/4)", text)
        self.assertIn("band flip share across 2 runs: 0.00", text)
        # 3 of 4 cases propose an edge per run; the ``test`` kind counts as added here.
        self.assertEqual(row_at(text, "0.60"), ["0.60", "1.00", "1.00", "6", "6", "<-", "confirm"])
        self.assertRegex(text, r"jev: 8 calls, \d+ input tokens, 0 failures")
        self.assertIn("PASS: target accuracy 1.00 (>= 0.90), precision 1.00 at confirm 0.60 (>= 0.95)", text)

    def test_state_uses_the_same_fallback_component_as_enrichment(self):
        jev = self.use(perfect)
        self.run_command("--runs", "1")
        # The eval has no topology, so every candidate gets ``component_for``'s
        # stand-in — the same one ``enrich_with_links`` builds for a candidate
        # outside the declared components (cassette keys hash this state).
        for (state, _questions), (c, _target, _kind) in zip(jev.calls, CASES):
            self.assertEqual(state, build_state(c, component_for(c)))
        self.assertEqual(
            jev.calls[0][0]["source_component"], {"name": "api-gateway", "path": "apps/api-gateway", "kind": "other"}
        )

    def test_one_wrong_edge_fails_the_bar(self):
        self.use(one_wrong)
        text = self.run_command("--runs", "1")

        self.assertIn("target accuracy: 0.75 (3/4)", text)
        self.assertIn("wrong: line 3 DATA_URL (env_var) expected none got roster:A band confirmed", text)
        # confusion: the none case landed in the roster column
        row = next(line for line in text.splitlines() if line.strip().startswith("none"))
        self.assertEqual(row.split(), ["none", "1", "0", "0", "0"])
        self.assertEqual(row_at(text, "0.60"), ["0.60", "0.75", "1.00", "4", "3", "<-", "confirm"])
        self.assertIn("FAIL: target accuracy 0.75 (< 0.90), precision 0.75 at confirm 0.60 (< 0.95)", text)

    def test_calibration_and_threshold_grid(self):
        self.use(perfect)
        text = self.run_command("--runs", "1", confirm="0.9")
        # link = 0.95 * 0.95 * 0.98 ≈ 0.884 → nothing is added at 0.90
        self.assertEqual(row_at(text, "0.90"), ["0.90", "0.00", "0.00", "0", "0", "<-", "confirm"])
        self.assertIn("0.8-0.9  n=3    right 1.00", text)
        self.assertNotIn("0.0-0.1", text)  # a "none" answer scores 0 and proposes no edge to calibrate
        self.assertIn("FAIL", text)
        thresholds = [row[0] for row in curve_rows(text)]
        self.assertEqual(thresholds[0], "0.50")
        self.assertEqual(thresholds[-1], "0.95")
        self.assertEqual(len(thresholds), 10)

    def test_bad_flags_are_command_errors(self):
        self.use(perfect)
        with self.assertRaisesRegex(CommandError, "exclusive"):
            self.run_command("--record", "a.json", "--replay", "b.json")
        with self.assertRaisesRegex(CommandError, "at least 1"):
            self.run_command("--runs", "0")
        with self.assertRaisesRegex(CommandError, "unsure"):
            self.run_command(confirm="0.6", unsure="0.7")

    def test_client_for_refuses_record_and_replay_together(self):
        with self.assertRaisesRegex(ValueError, "exclusive"):
            client_for(record="a.json", replay="b.json")

    def test_no_client_is_a_clear_error(self):
        use_jev(self.monkeypatch, None)
        with self.assertRaisesRegex(CommandError, "Jev is not configured.*--replay"):
            self.run_command()

    def test_record_wraps_the_client_and_writes_a_cassette(self):
        self.use(perfect)
        cassette = self.tmp_path / "cassette.json"
        self.run_command("--runs", "1", "--record", str(cassette))
        self.assertEqual(len(json.loads(cassette.read_text())), 4)

        # …and the cassette replays without a client.
        use_jev(self.monkeypatch, None)
        text = self.run_command("--runs", "1", "--replay", str(cassette))
        self.assertIn("target accuracy: 1.00 (4/4)", text)
        self.assertIn("PASS", text)
