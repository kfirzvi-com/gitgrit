"""Score an inference against a golden topology, without storing anything.

  manage.py eval_topology <project_id> --local-path ../repo --golden tests/fixtures/topology/repo.json
  manage.py eval_topology <project_id> --local-path ../repo --golden … --fixture other.json   # sanity: fixture vs golden
  manage.py eval_topology … --save-json out.json                                          # keep the inferred topology

The model is non-deterministic, so this is a scored comparison (precision /
recall per section), not an exact assertion. Run on demand when touching the
prompts or swapping the inference adapter; it is not part of the CI suite.

Sections and their keys:
  components      component path
  internal        (source path, resolved target ref)
  externals       (source path, canonical name, direction)
  infrastructure  (source path, kind)
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from app.application.architecture.ports import InferenceContext
from app.application.architecture.refresh import workspace_roster
from app.domain.architecture.naming import canonical_key
from app.domain.architecture.resolve import RosterEntry, resolve_topology
from app.domain.architecture.topology import RepositoryTopology
from app.domain.models import Project


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
    for section in ("components", "internal", "externals", "infrastructure"):
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


class Command(BaseCommand):
    help = "Run topology inference on a repository and score it against a golden file."

    def add_arguments(self, parser):
        parser.add_argument("project_id", help="Project whose workspace/roster/LLM role to use")
        parser.add_argument("--local-path", required=True, help="Checkout of the repository to analyse")
        parser.add_argument("--golden", required=True, help="Golden topology JSON")
        parser.add_argument("--fixture", help="Use this topology JSON instead of the model (sanity check)")
        parser.add_argument("--save-json", help="Write the inferred topology here")

    def handle(self, *args, **opts):
        from app.infrastructure.topology.snapshots import LocalDirSnapshot

        project = Project.objects.filter(pk=opts["project_id"]).first()
        if project is None:
            raise CommandError("No such project")

        snapshot = LocalDirSnapshot(opts["local_path"])
        if opts.get("fixture"):
            from app.infrastructure.topology.fake import FakeTopologyInference

            inference = FakeTopologyInference.from_file(opts["fixture"])
        else:
            from app.application.dependency_agent import llm_inference_for

            inference = llm_inference_for(project.tenant)

        roster = workspace_roster(project)
        context = InferenceContext(
            project_name=project.name,
            full_path=project.full_path,
            roster=roster,
            log=lambda m: self.stderr.write(f"  · {m}"),
        )
        inferred = inference.infer(snapshot, context)
        if opts.get("save_json"):
            with open(opts["save_json"], "w", encoding="utf-8") as fh:
                json.dump(inferred.to_dict(), fh, indent=2)

        with open(opts["golden"], encoding="utf-8") as fh:
            golden = _expand(RepositoryTopology.from_dict(json.load(fh)), project.full_path)

        # Both sides resolve against the same roster: the workspace plus the
        # golden's own components as siblings (what a stored run would see).
        siblings = tuple(
            RosterEntry(full_path=project.full_path, path=c.path, name=c.name) for c in golden.components
        )
        full_roster = roster + siblings
        rows = score(_keys(inferred, full_roster, project.full_path), _keys(golden, full_roster, project.full_path))

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
