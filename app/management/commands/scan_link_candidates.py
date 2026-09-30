"""Dump link candidates for a repository as a JSONL case file.

  manage.py scan_link_candidates <project_id> --local-path ../repo --out cases.jsonl
  manage.py scan_link_candidates <project_id> --local-path ../repo --fixture golden.json --out cases.jsonl

Components come from ``--fixture`` (a topology JSON) or default to a single
root component; the roster is the project's workspace plus the fixture's
components as siblings. Each line is one candidate (``dataclasses.asdict``)
plus two empty fields, ``expected_target`` and ``expected_kind``, to be filled
by hand — the result is the case file ``eval_jev_links`` scores against.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict

from django.core.management.base import BaseCommand

from app.application.architecture.ports import InferenceContext
from app.application.architecture.refresh import workspace_roster
from app.domain.architecture.links import DEFAULT_LIMIT, find_link_candidates
from app.domain.architecture.resolve import with_siblings
from app.domain.architecture.topology import ComponentDecl
from app.management.commands._projects import project_or_command_error


class Command(BaseCommand):
    help = "Scan a repository checkout for link candidates and write them as JSONL cases."

    def add_arguments(self, parser):
        parser.add_argument("project_id", help="Project whose workspace roster to use")
        parser.add_argument("--local-path", required=True, help="Checkout of the repository to scan")
        parser.add_argument("--fixture", help="Topology JSON whose components define the sources")
        parser.add_argument("--out", required=True, help="JSONL file to write")
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Max candidates (default {DEFAULT_LIMIT})")

    def handle(self, *args, **opts):
        from app.infrastructure.topology.snapshots import LocalDirSnapshot

        project = project_or_command_error(opts["project_id"])
        snapshot = LocalDirSnapshot(opts["local_path"])
        roster = workspace_roster(project)
        if opts.get("fixture"):
            from app.infrastructure.topology.fake import FakeTopologyInference

            context = InferenceContext(
                project_name=project.name,
                full_path=project.full_path,
                roster=roster,
                log=lambda m: self.stderr.write(f"  · {m}"),
            )
            components = FakeTopologyInference.from_file(opts["fixture"]).infer(snapshot, context).components
        else:
            components = (ComponentDecl(path="", name=project.name),)

        full_roster = with_siblings(roster, project.full_path, components)
        scan = find_link_candidates(
            snapshot.list_files(),
            snapshot.read_file,
            components,
            full_roster,
            this_repo=project.full_path,
            limit=opts["limit"],
        )

        with open(opts["out"], "w", encoding="utf-8") as fh:
            for candidate in scan.candidates:
                row = {**asdict(candidate), "expected_target": "", "expected_kind": ""}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

        by_kind = Counter(c.reference_kind for c in scan.candidates)
        self.stdout.write(
            f"{len(scan.candidates)} candidates from {len(scan.files_read)} files -> {opts['out']}"
        )
        for kind, n in by_kind.most_common():
            self.stdout.write(f"  {kind:<20}{n:>4}")
