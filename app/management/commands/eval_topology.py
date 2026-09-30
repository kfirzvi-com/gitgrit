"""Score an inference against a golden topology, without storing anything.

  manage.py eval_topology <project_id> --local-path ../repo --golden tests/fixtures/topology/repo.json
  manage.py eval_topology <project_id> --local-path ../repo --golden … --fixture other.json   # sanity: fixture vs golden
  manage.py eval_topology … --save-json out.json                                          # keep the inferred topology
  manage.py eval_topology … --runs 5                                                      # repeat, then summarise
  manage.py eval_topology … --fixture d1.json --fixture d2.json --fixture d3.json         # one run per fixture
  manage.py eval_topology … --jev on [--record-jev c.json | --replay-jev c.json]          # add the Jev link stage

The model is non-deterministic, so this is a scored comparison (precision /
recall per section), not an exact assertion. Run on demand when touching the
prompts or swapping the inference adapter; it is not part of the CI suite.

Sections and their keys:
  components      component path
  internal        (source path, resolved target ref)
  externals       (source path, canonical name, direction)
  infrastructure  (source path, kind)

With ``--runs N`` every run prints its own table, then a summary block gives
per section the mean precision / recall / F1 over the runs and the *flip
rate*: the mean Jaccard distance between consecutive runs' edge sets
(``internal`` ∪ ``externals`` keys). ``--save-json out.json`` becomes
``out-run1.json``, ``out-run2.json``, … when N > 1.

``--fixture`` may be repeated: each fixture is then one run, in order (``--runs``
must stay 1), so the flip rate becomes the agreement between fixtures — e.g.
three LLM drafts of the same repository, with and without ``--jev on``.

``--jev on`` wraps the chosen inference in ``LinkEnrichedInference`` (the
code-scanned candidate links judged by Jev). The Jev client comes from the
settings, is recorded to a cassette with ``--record-jev``, or is replaced by a
cassette replay with ``--replay-jev`` (no key or network needed). After the
runs the block also prints Jev calls, input tokens, decisions per band and
the verdicts on the LLM's own edges (kept / moved / removed / no_evidence).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from app.application.architecture.ports import InferenceContext
from app.application.architecture.refresh import workspace_roster
from app.domain.architecture.eval_metrics import (  # noqa: F401 — re-exported for tests
    EDGE_SECTIONS,
    SECTIONS,
    edge_keys,
    f1,
    flip_rate,
    jaccard_distance,
    summarize,
)
from app.domain.architecture.naming import canonical_key
from app.domain.architecture.resolve import resolve_topology, with_siblings
from app.domain.architecture.topology import RepositoryTopology
from app.infrastructure.jev import JevNotConfigured, client_for
from app.infrastructure.topology.jev_links import BANDS, VERDICTS, LinkEnrichedInference
from app.management.commands._projects import project_or_command_error


def _keys(topology: RepositoryTopology, roster, full_path: str) -> dict[str, set]:
    resolved = resolve_topology(topology, roster, this_repo=full_path)
    return {
        "components": {c.path for c in topology.components},
        "internal": {(r.source_path, r.target.ref) for r in resolved.internal},
        "externals": {(e.source_path, canonical_key(e.name), e.direction) for e in resolved.externals},
        "infrastructure": {(i.source_path, i.kind) for i in resolved.infrastructure},
    }


def _expand(topology: RepositoryTopology, full_path: str) -> RepositoryTopology:
    from dataclasses import replace

    return replace(
        topology,
        internal=tuple(
            replace(d, target_ref=d.target_ref.replace("{repo}", full_path)) for d in topology.internal
        ),
    )


def score(inferred: dict[str, set], golden: dict[str, set]) -> list[dict]:
    rows = []
    for section in SECTIONS:
        got, want = inferred[section], golden[section]
        hit = got & want
        precision = len(hit) / len(got) if got else (1.0 if not want else 0.0)
        recall = len(hit) / len(want) if want else 1.0
        rows.append(
            {
                "section": section,
                "expected": len(want),
                "inferred": len(got),
                "hit": len(hit),
                "precision": round(precision, 2),
                "recall": round(recall, 2),
                "missed": sorted(map(str, want - got)),
                "extra": sorted(map(str, got - want)),
            }
        )
    return rows


def run_output_path(save_json: str, run: int, runs: int) -> Path:
    """``out.json`` → ``out-run<N>.json`` when there is more than one run."""
    path = Path(save_json)
    if runs <= 1:
        return path
    return path.with_name(f"{path.stem}-run{run}{path.suffix}")


class Command(BaseCommand):
    help = "Run topology inference on a repository and score it against a golden file."

    def add_arguments(self, parser):
        parser.add_argument("project_id", help="Project whose workspace/roster/LLM role to use")
        parser.add_argument("--local-path", required=True, help="Checkout of the repository to analyse")
        parser.add_argument("--golden", required=True, help="Golden topology JSON")
        parser.add_argument(
            "--fixture",
            action="append",
            help="Use this topology JSON instead of the model; repeat it for one run per fixture",
        )
        parser.add_argument("--save-json", help="Write the inferred topology here (-run<N> suffix when --runs > 1)")
        parser.add_argument("--runs", type=int, default=1, help="Repeat the inference N times and summarise")
        parser.add_argument(
            "--jev", choices=("on", "off"), default="off", help="Add the Jev link stage on top of the inference"
        )
        parser.add_argument("--record-jev", metavar="PATH", help="Record every Jev call to this cassette")
        parser.add_argument("--replay-jev", metavar="PATH", help="Answer Jev calls from this cassette (no key needed)")

    def handle(self, *args, **opts):
        from app.infrastructure.topology.snapshots import LocalDirSnapshot

        runs = opts["runs"]
        fixtures = opts.get("fixture") or []
        if runs < 1:
            raise CommandError("--runs must be at least 1")
        if len(fixtures) > 1:
            if runs != 1:
                raise CommandError("--runs must be 1 (or omitted) with more than one --fixture: each fixture is one run")
            runs = len(fixtures)
        if opts["jev"] == "off" and (opts.get("record_jev") or opts.get("replay_jev")):
            raise CommandError("--record-jev / --replay-jev need --jev on")
        if opts.get("record_jev") and opts.get("replay_jev"):
            raise CommandError("--record-jev and --replay-jev are exclusive")
        project = project_or_command_error(opts["project_id"])

        snapshot = LocalDirSnapshot(opts["local_path"])
        jev = self._jev_client(opts)
        inners = [self._inner(project, fixture) for fixture in fixtures] or [self._inner(project, None)]
        roster = workspace_roster(project)
        context = InferenceContext(
            project_name=project.name,
            full_path=project.full_path,
            roster=roster,
            log=lambda m: self.stderr.write(f"  · {m}"),
        )
        full_roster, golden_keys = self._load_golden(opts, project, roster)

        rows_per_run: list[list[dict]] = []
        edge_sets: list[set] = []
        bands: Counter = Counter()
        verdicts: Counter = Counter()
        for run in range(1, runs + 1):
            inner = inners[run - 1] if len(inners) > 1 else inners[0]
            inference = LinkEnrichedInference(inner, jev) if jev is not None else inner
            if len(fixtures) > 1:
                self.stdout.write(f"\n=== run {run}/{runs} (fixture {Path(fixtures[run - 1]).name}) ===")
            elif runs > 1:
                self.stdout.write(f"\n=== run {run}/{runs} ===")
            inferred = inference.infer(snapshot, context)
            if opts.get("save_json"):
                out = run_output_path(opts["save_json"], run, runs)
                with open(out, "w", encoding="utf-8") as fh:
                    json.dump(inferred.to_dict(), fh, indent=2)

            keys = _keys(inferred, full_roster, project.full_path)
            rows = score(keys, golden_keys)
            rows_per_run.append(rows)
            edge_sets.append(edge_keys(keys))
            if jev is not None:
                bands.update(d.band for d in inference.decisions if d.asked)
                verdicts.update(d.verdict for d in inference.decisions if d.verdict)
            self._print_run(rows, inferred)

        self._print_summary(rows_per_run, edge_sets, jev, bands, verdicts)

    # --- helpers ---------------------------------------------------------------

    def _inner(self, project, fixture: str | None):
        """The inference under test: ``fixture`` or the workspace LLM."""
        if fixture:
            from app.infrastructure.topology.fake import FakeTopologyInference

            return FakeTopologyInference.from_file(fixture)
        from app.application.dependency_agent import llm_inference_for

        return llm_inference_for(project.tenant)

    def _jev_client(self, opts):
        """The Jev client for ``--jev on`` (settings, recorder or replay), None
        when the stage is off. Every run's ``LinkEnrichedInference`` shares it
        so the usage block covers the whole command."""
        if opts["jev"] == "off":
            return None
        try:
            return client_for(record=opts.get("record_jev"), replay=opts.get("replay_jev"))
        except JevNotConfigured as exc:
            raise CommandError(f"{exc}, or pass --replay-jev <cassette>") from exc

    def _load_golden(self, opts, project, roster):
        """The golden topology's keys, resolved like a stored run would be:
        against the workspace roster plus the golden's own components as
        siblings. Returns ``(full_roster, golden_keys)``; the inferred side
        resolves against the same ``full_roster``."""
        with open(opts["golden"], encoding="utf-8") as fh:
            golden = _expand(RepositoryTopology.from_dict(json.load(fh)), project.full_path)
        full_roster = with_siblings(roster, project.full_path, golden.components)
        return full_roster, _keys(golden, full_roster, project.full_path)

    def _print_run(self, rows: list[dict], inferred: RepositoryTopology):
        self.stdout.write(f"\n{'section':<15}{'exp':>5}{'got':>5}{'hit':>5}{'prec':>7}{'rec':>7}")
        for r in rows:
            self.stdout.write(
                f"{r['section']:<15}{r['expected']:>5}{r['inferred']:>5}{r['hit']:>5}"
                f"{r['precision']:>7}{r['recall']:>7}"
            )
        for r in rows:
            for label in ("missed", "extra"):
                for item in r[label]:
                    self.stdout.write(f"  {r['section']} {label}: {item}")
        self.stdout.write(
            f"\nevidence: {inferred.evidence.tree_size} files in tree, "
            f"{len(inferred.evidence.files_read)} read"
        )

    def _print_summary(
        self,
        rows_per_run: list[list[dict]],
        edge_sets: list[set],
        jev: object | None,
        bands: Counter,
        verdicts: Counter,
    ):
        runs = len(rows_per_run)
        self.stdout.write(f"\n=== summary over {runs} run{'s' if runs != 1 else ''} ===")
        self.stdout.write(f"{'section':<15}{'prec':>7}{'rec':>7}{'f1':>7}")
        for section, m in summarize(rows_per_run).items():
            self.stdout.write(
                f"{section:<15}{m['precision']:>7.2f}{m['recall']:>7.2f}{m['f1']:>7.2f}"
            )
        self.stdout.write(f"flip rate (internal ∪ externals): {flip_rate(edge_sets):.2f}")
        if jev is None:
            return
        usage = jev.usage
        self.stdout.write(
            f"jev: {usage['calls']} calls, {usage['input_tokens']} input tokens, "
            f"{usage['failures']} failures"
        )
        order = BANDS + tuple(sorted(b for b in bands if b not in BANDS))
        self.stdout.write("jev decisions: " + ", ".join(f"{band} {bands.get(band, 0)}" for band in order))
        self.stdout.write("jev verdicts: " + ", ".join(f"{v} {verdicts.get(v, 0)}" for v in VERDICTS))

