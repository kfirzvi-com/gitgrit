"""Fixture-driven inference: the topology is read from a dict/JSON file.

For tests and for local development without an LLM key
(``refresh_project_deps --fixture path.json``). A fixture describes a whole
repository — its ``units`` (each a path inside it) and edges keyed by
``source_path`` — so one file serves every project added from it: the
project at a unit's path gets that unit's edges, the whole-repository project
also gets every unit as a suggested project. ``{repo}`` inside an internal
target ref expands to the analysed repository's full path, so one fixture
works whatever organisation the demo repository is registered under.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.application.architecture.ports import InferenceContext, RepositorySnapshot
from app.domain.architecture.topology import Evidence, ProjectTopology


class FakeTopologyInference:
    """Answers with ``source``: a whole-repository description (a dict, each
    project gets its slice) or one ``ProjectTopology`` for every project."""

    def __init__(self, source: dict | ProjectTopology, *, read_files: bool = True):
        self._source = source
        self._read_files = read_files
        self.contexts: list[InferenceContext] = []

    @classmethod
    def from_file(cls, path: str | Path) -> "FakeTopologyInference":
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def infer(self, snapshot: RepositorySnapshot, context: InferenceContext) -> ProjectTopology:
        self.contexts.append(context)
        if isinstance(self._source, ProjectTopology):
            topology = self._source
        else:
            topology = ProjectTopology.of_repository(self._source, context.root_path)
        topology = replace(
            topology,
            internal=tuple(
                replace(d, target_ref=d.target_ref.replace("{repo}", context.full_path))
                for d in topology.internal
            ),
            suggestions=topology.suggestions if context.discover else (),
        )
        if self._read_files:
            # Behave like a grounded run: list the tree and read the fixture's
            # evidence files (or the first manifest we can find).
            tree = snapshot.list_files()
            wanted = list(topology.evidence.files_read) or [
                f for f in tree if f.rsplit("/", 1)[-1].lower() in ("readme.md", "package.json", "pyproject.toml", "go.mod")
            ][:3]
            read = tuple(p for p in wanted if snapshot.read_file(p) is not None)
            topology = replace(topology, evidence=Evidence(tree_size=len(tree), files_read=read))
        return topology
