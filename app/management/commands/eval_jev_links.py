"""Score Jev's link judgments against hand-labelled candidates (plan §4b).

The case file is hand-curated and never regenerated, so scanner changes (for
example to snippet masking) do not move these scores.

  manage.py eval_jev_links --cases tests/fixtures/jev/link_candidates.jsonl
  manage.py eval_jev_links --cases cases.jsonl --runs 5 --record cassette.json    # real Jev, keep the answers
  manage.py eval_jev_links --cases cases.jsonl --replay cassette.json             # offline, no key
  manage.py eval_jev_links --cases cases.jsonl --confirm 0.85 --unsure 0.30       # try other cut-offs

Each JSONL line is one ``LinkCandidate`` as ``scan_link_candidates`` writes it
plus ``expected_target`` (``<ref>`` | ``external:<name>`` | ``none``) and
``expected_kind`` (one of the edge kinds, or empty when unlabelled). Lines
whose ``expected_target`` is empty are skipped, so a half-labelled file works.

Reported: target accuracy, edge-kind accuracy where labelled, the confusion
between roster / external / none, precision and recall of "add an edge" at
every threshold 0.50…0.95, calibration by ``link`` bucket, band flip share
across runs, tokens and latency, and the pass bar for going on to the
map-level eval: target accuracy ≥ 0.90 and precision ≥ 0.95 at ``--confirm``.
Runs are pooled: every metric is over all cases × all runs.

The precision/recall curve and the calibration threshold ``Decision.link``,
which is 0 whenever no edge could be added (Jev chose ``none``, an external
with no code-derived name, or failed). The curve measures *target* precision:
an edge counts as right when the chosen target is the labelled one. ``test``
and ``dev_only`` kinds count as "added" here although production never draws
them — the curve is about whether Jev picks the right target, not about what
the map shows.
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from app.domain.architecture.eval_metrics import (
    accuracy,
    calibration_buckets,
    confusion,
    flip_share,
    precision_recall_at,
    threshold_grid,
)
from app.domain.architecture.links import LinkCandidate, TargetOption
from app.domain.architecture.naming import canonical_key
from app.infrastructure.jev import JevNotConfigured, client_for
from app.infrastructure.topology.jev_links import (
    Decision,
    Thresholds,
    build_questions,
    build_state,
    component_for,
    decide_all,
)

PASS_TARGET_ACCURACY = 0.90
PASS_PRECISION = 0.95
CLASSES = ("roster", "external", "none")
PREDICTED_CLASSES = CLASSES + ("failed",)

CANDIDATE_FIELDS = {f.name for f in fields(LinkCandidate)}


def load_cases(path: str | Path) -> list[dict]:
    """The labelled lines of a case file: ``{"candidate", "expected_target", "expected_kind"}``."""
    cases = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            expected = (row.get("expected_target") or "").strip()
            if not expected:
                continue
            data = {k: v for k, v in row.items() if k in CANDIDATE_FIELDS}
            data["options"] = tuple(TargetOption(**o) for o in row.get("options", ()))
            cases.append(
                {
                    "line": n,
                    "candidate": LinkCandidate(**data),
                    "expected_target": expected,
                    "expected_kind": (row.get("expected_kind") or "").strip(),
                }
            )
    return cases


def expected_class(expected_target: str) -> str:
    if expected_target == "none":
        return "none"
    if expected_target.startswith("external:"):
        return "external"
    return "roster"


def predicted_class(decision: Decision) -> str:
    if decision.band == "failed":
        return "failed"
    if decision.choice == "none":
        return "none"
    if decision.choice == "external":
        return "external"
    return "roster"


def normalized_target(expected_target: str) -> str:
    kind = expected_class(expected_target)
    if kind == "none":
        return "none"
    if kind == "external":
        return "external:" + canonical_key(expected_target[len("external:"):])
    return expected_target.lower()


def chosen_target(decision: Decision) -> str | None:
    """What Jev's ``target`` choice denotes, in the label's spelling — whatever
    the band, so accuracy measures the pick and not the cut-offs."""
    if decision.band == "failed":
        return None
    c = decision.candidate
    if decision.choice == "none":
        return "none"
    if decision.choice == "external":
        return "external:" + canonical_key(c.external_name) if c.external_name else "external:"
    return {o.id: o.ref.lower() for o in c.options}.get(decision.choice or "")


def target_is_right(decision: Decision, expected_target: str) -> bool:
    return chosen_target(decision) == normalized_target(expected_target)


class Command(BaseCommand):
    help = "Score Jev's link decisions against a labelled JSONL case file."

    def add_arguments(self, parser):
        parser.add_argument("--cases", required=True, help="JSONL case file (see scan_link_candidates)")
        parser.add_argument("--runs", type=int, default=5, help="Ask every case N times (default 5)")
        parser.add_argument("--record", metavar="PATH", help="Record every Jev call to this cassette")
        parser.add_argument("--replay", metavar="PATH", help="Answer Jev calls from this cassette (no key needed)")
        parser.add_argument("--confirm", type=float, default=Thresholds.confirm, help="Confirmed band cut-off")
        parser.add_argument("--unsure", type=float, default=Thresholds.unsure, help="Unsure band cut-off")
        parser.add_argument("--workers", type=int, default=8)

    def handle(self, *args, **opts):
        if opts["runs"] < 1:
            raise CommandError("--runs must be at least 1")
        if opts.get("record") and opts.get("replay"):
            raise CommandError("--record and --replay are exclusive")
        if not 0 <= opts["unsure"] <= opts["confirm"] <= 1:
            raise CommandError("need 0 ≤ --unsure ≤ --confirm ≤ 1")
        thresholds = Thresholds(confirm=opts["confirm"], unsure=opts["unsure"])

        cases = load_cases(opts["cases"])
        if not cases:
            raise CommandError(f"no labelled cases in {opts['cases']} (fill expected_target)")
        jev = self._jev_client(opts)

        by_class = confusion((expected_class(c["expected_target"]), "") for c in cases)
        self.stdout.write(
            f"cases: {len(cases)} ("
            + ", ".join(f"{k} {by_class.get((k, ''), 0)}" for k in CLASSES)
            + f"), runs: {opts['runs']}, confirm {thresholds.confirm:.2f}, unsure {thresholds.unsure:.2f}"
        )

        items = [(i, build_state(c["candidate"], component_for(c["candidate"])), build_questions(c["candidate"]))
                 for i, c in enumerate(cases)]
        decisions_per_run: list[list[Decision]] = []
        for run in range(1, opts["runs"] + 1):
            results = jev.ask_many(items, workers=opts["workers"])
            decisions = decide_all([c["candidate"] for c in cases], results, thresholds)
            decisions_per_run.append(decisions)
            hits = sum(1 for c, d in zip(cases, decisions) if target_is_right(d, c["expected_target"]))
            self.stdout.write(
                f"run {run}/{opts['runs']}: target accuracy {accuracy(hits, len(cases)):.2f} ({hits}/{len(cases)})"
            )

        self._report(cases, decisions_per_run, thresholds, jev)

    # --- helpers ---------------------------------------------------------------

    def _jev_client(self, opts):
        try:
            return client_for(record=opts.get("record"), replay=opts.get("replay"))
        except JevNotConfigured as exc:
            raise CommandError(f"{exc}, or pass --replay <cassette>") from exc

    def _report(self, cases, decisions_per_run, thresholds: Thresholds, jev):
        pooled = [(c, d) for decisions in decisions_per_run for c, d in zip(cases, decisions)]

        # Target / kind accuracy.
        right = sum(1 for c, d in pooled if target_is_right(d, c["expected_target"]))
        target_acc = accuracy(right, len(pooled))
        self.stdout.write(f"\ntarget accuracy: {target_acc:.2f} ({right}/{len(pooled)})")
        labelled = [(c, d) for c, d in pooled if c["expected_kind"]]
        kind_right = sum(1 for c, d in labelled if d.edge_kind == c["expected_kind"])
        if labelled:
            self.stdout.write(
                f"edge_kind accuracy: {accuracy(kind_right, len(labelled)):.2f} ({kind_right}/{len(labelled)})"
            )
        else:
            self.stdout.write("edge_kind accuracy: n/a (no expected_kind labels)")
        wrong = [(c, d) for c, d in pooled if not target_is_right(d, c["expected_target"])]
        for c, d in wrong[:20]:
            self.stdout.write(
                f"  wrong: line {c['line']} {c['candidate'].reference} ({c['candidate'].reference_kind}) "
                f"expected {c['expected_target']} got {predicted_class(d)}:{d.choice} "
                f"band {d.band} link {d.link:.2f}"
                + (f" error {d.error}" if d.error else "")
            )

        # Confusion.
        matrix = confusion((expected_class(c["expected_target"]), predicted_class(d)) for c, d in pooled)
        self.stdout.write("\nconfusion (expected ↓ / predicted →):")
        self.stdout.write(f"  {'':<10}" + "".join(f"{p:>10}" for p in PREDICTED_CLASSES))
        for e in CLASSES:
            self.stdout.write(f"  {e:<10}" + "".join(f"{matrix.get((e, p), 0):>10}" for p in PREDICTED_CLASSES))

        # Precision / recall of "add an edge" (target precision; see the module doc).
        scored = [
            (d.link, expected_class(c["expected_target"]) != "none", target_is_right(d, c["expected_target"]))
            for c, d in pooled
        ]
        grid = threshold_grid()
        if round(thresholds.confirm, 2) not in grid:
            grid = sorted(set(grid) | {round(thresholds.confirm, 2)})
        curve = precision_recall_at(scored, grid)
        self.stdout.write('\nprecision/recall of "add edge":')
        self.stdout.write(f"  {'thr':<4}{'prec':>7}{'rec':>7}{'added':>7}{'tp':>5}")
        for row in curve:
            mark = "  <- confirm" if row["threshold"] == round(thresholds.confirm, 2) else ""
            self.stdout.write(
                f"  {row['threshold']:.2f}{row['precision']:>7.2f}{row['recall']:>7.2f}"
                f"{row['added']:>7}{row['tp']:>5}{mark}"
            )
        at_confirm = next(r for r in curve if r["threshold"] == round(thresholds.confirm, 2))

        # Calibration.
        self.stdout.write("\ncalibration of proposed edges (link bucket -> share right):")
        proposed = [(link, positive and correct) for link, positive, correct in scored if link > 0]
        for b in calibration_buckets(proposed):
            self.stdout.write(f"  {b['lo']:.1f}-{b['hi']:.1f}  n={b['n']:<4} right {b['share']:.2f}")

        # Stability, cost.
        share = flip_share([[d.band for d in decisions] for decisions in decisions_per_run])
        self.stdout.write(f"\nband flip share across {len(decisions_per_run)} runs: {share:.2f}")
        results = [d.result for _, d in pooled if d.result is not None]
        tokens = sum(r.input_tokens for r in results)
        latency = sum(r.latency_ms for r in results) / len(results) if results else 0.0
        usage = jev.usage
        self.stdout.write(
            f"jev: {usage['calls']} calls, {usage['input_tokens']} input tokens, {usage['failures']} failures; "
            f"{tokens / len(pooled):.0f} tokens and {latency:.0f} ms per candidate"
        )

        passed = target_acc >= PASS_TARGET_ACCURACY and at_confirm["precision"] >= PASS_PRECISION
        self.stdout.write(
            f"\n{'PASS' if passed else 'FAIL'}: target accuracy {target_acc:.2f} "
            f"({'>=' if target_acc >= PASS_TARGET_ACCURACY else '<'} {PASS_TARGET_ACCURACY:.2f}), "
            f"precision {at_confirm['precision']:.2f} at confirm {thresholds.confirm:.2f} "
            f"({'>=' if at_confirm['precision'] >= PASS_PRECISION else '<'} {PASS_PRECISION:.2f})"
        )
