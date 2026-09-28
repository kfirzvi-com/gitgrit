"""``TopologyInference`` read from the repository's ``.gitgrit.yml``.

No model: the file already holds what the two LLM phases would return. The
repository is read through ``RepoToolbox`` so the evidence (``tree_size``,
``files_read``) is recorded exactly like an LLM run, and the components go
through the same ``normalise_components`` rules.

Raises ``MapFileMissing`` when the repository has no map file and
``InvalidMapFile`` when it breaks the format; the caller decides whether to
fall back to the LLM.
"""
from __future__ import annotations

from dataclasses import replace

from app.application.architecture.ports import InferenceContext, RepositorySnapshot
from app.domain.architecture.map_file import MAP_FILE, InvalidMapFile, parse_map_file
from app.domain.architecture.topology import Evidence, RepositoryTopology, normalise_components
from app.infrastructure.topology.toolbox import RepoToolbox

__all__ = ["InvalidMapFile", "MapFileInference", "MapFileMissing"]


class MapFileMissing(LookupError):
    """The repository has no readable ``.gitgrit.yml`` at its root."""


class MapFileInference:
    def infer(self, snapshot: RepositorySnapshot, context: InferenceContext) -> RepositoryTopology:
        toolbox = RepoToolbox(snapshot, context.full_path)
        tree = toolbox.load_tree()
        if MAP_FILE not in tree:
            raise MapFileMissing(f"no {MAP_FILE} in the repository")
        read_before = len(toolbox.files_read)
        text = toolbox.read_file(MAP_FILE)
        if len(toolbox.files_read) == read_before:
            raise MapFileMissing(f"{MAP_FILE} is not a readable text file")

        # Paths are checked against every folder: a developer may list one the
        # LLM's listing hides as noise (vendor/, build/, dist/).
        files = toolbox.all_files
        parsed = parse_map_file(text, files)
        components = normalise_components(parsed.components, files, context.project_name)
        # A single component is always the root (normalise_components); its
        # dependencies follow it there.
        moved = {parsed.components[0].path: components[0].path} if len(parsed.components) == 1 else {}

        def at(entry):
            return replace(entry, source_path=moved.get(entry.source_path, entry.source_path))

        topology = RepositoryTopology(
            components=components,
            internal=tuple(at(d) for d in parsed.internal),
            externals=tuple(at(e) for e in parsed.externals),
            infrastructure=tuple(at(i) for i in parsed.infrastructure),
            evidence=Evidence(tree_size=toolbox.tree_size, files_read=tuple(toolbox.files_read)),
            source="file",
            map_text=text,
        )
        context.log(
            f"{MAP_FILE}: {len(topology.components)} components, {len(topology.internal)} internal, "
            f"{len(topology.infrastructure)} infra, {len(topology.externals)} external (no LLM calls)"
        )
        return topology
