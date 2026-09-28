"""Entry point for dependency inference: wires the production adapters into
the ``RefreshProjectTopology`` use case.

Kept as the one name the task, the management command and the subscribers
call (``infer_and_store``), so the composition root is the only place that
knows which snapshot and which inference are in use. Pass ``inference`` /
``snapshot`` to run against a fixture or a local checkout instead.

By default the repository's ``.gitgrit.yml`` is read first; the LLM runs only
when the file is missing or invalid, so its role is looked up only then.
"""
from __future__ import annotations

from app.application.architecture.ports import (
    InferenceContext,
    RepositorySnapshot,
    TopologyInference,
)
from app.application.architecture.refresh import InferenceSummary, RefreshProjectTopology
from app.application.standard_engine import resolve_llm_roles
from app.domain.architecture.map_file import MAP_FILE, InvalidMapFile
from app.domain.architecture.topology import RepositoryTopology
from app.domain.models import Project
from app.infrastructure.topology.llm_inference import ROLE, LLMTopologyInference
from app.infrastructure.topology.map_file import MapFileInference, MapFileMissing
from app.infrastructure.topology.snapshots import snapshot_for_project


def llm_inference_for(tenant) -> LLMTopologyInference:
    """The workspace's configured reasoning model as a ``TopologyInference``."""
    cfg = resolve_llm_roles(tenant).get(ROLE)
    if not cfg:
        raise RuntimeError(
            f"No '{ROLE}' LLM role configured for this workspace — set it under "
            "Workspace Settings → LLM."
        )
    return LLMTopologyInference(cfg)


class FileFirstInference:
    """The repository's ``.gitgrit.yml`` when it is present and valid, else the
    workspace's LLM (looked up only then, so a valid file needs no LLM role)."""

    def __init__(self, tenant):
        self._tenant = tenant

    def infer(self, snapshot: RepositorySnapshot, context: InferenceContext) -> RepositoryTopology:
        try:
            return MapFileInference().infer(snapshot, context)
        except MapFileMissing as exc:
            context.log(f"{exc} — running the LLM analysis")
        except InvalidMapFile as exc:
            context.log(f"{MAP_FILE} is invalid ({exc}) — running the LLM analysis")
        return llm_inference_for(self._tenant).infer(snapshot, context)


def _enqueue_refresh(project_id: str) -> None:
    from app.application.subscribers import _enqueue_dependency_refresh

    _enqueue_dependency_refresh(project_id)


def infer_and_store(
    project: Project,
    *,
    inference: TopologyInference | None = None,
    snapshot: RepositorySnapshot | None = None,
) -> InferenceSummary:
    """Analyze one project's repository and replace its components and edges.

    Sets the project's deps_status to OK on success; raises on failure (the
    caller/task records the failure and the previous map is kept).
    """
    use_case = RefreshProjectTopology(
        inference=inference or FileFirstInference(project.tenant),
        snapshot_factory=(lambda p: snapshot) if snapshot is not None else snapshot_for_project,
        enqueue_refresh=_enqueue_refresh,
    )
    return use_case.run(project)
