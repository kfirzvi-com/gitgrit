"""Refresh one project's dependency edges.

The single write path for the architecture graph. Given an inference (LLM,
fixture, …) and a way to snapshot the repository, it:

1. infers a ``ProjectTopology`` for the project, scoped to its root path and
   leaving out the directories other projects on the repository own;
2. refuses one that was never grounded in the repository (evidence gate) so
   the previous map survives a bad run;
3. resolves the topology's names against the workspace roster (every other
   project);
4. in one transaction, replaces the project's edges, externals and
   infrastructure, its tech labels and — for a whole-repository project —
   the projects suggested from inside its repository.

Stack-to-stack edges are NOT written here; they are derived at read time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from django.db import transaction
from django.utils import timezone

from app.application.architecture.ports import (
    InferenceContext,
    RepositorySnapshot,
    TopologyInference,
)
from app.domain.architecture.resolve import RosterEntry, resolve_topology
from app.domain.architecture.topology import INBOUND, MAX_EVIDENCE_FILES, check_evidence
from app.domain.models import (
    ExternalDependency,
    InfrastructureComponent,
    Project,
    ProjectDependency,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceSummary:
    internal: int
    infrastructure: int
    providers: int
    consumers: int
    files_read: int
    suggestions: int = 0
    unresolved: tuple[str, ...] = ()

    @property
    def external(self) -> int:
        return self.providers + self.consumers


def workspace_roster(project: Project) -> tuple[RosterEntry, ...]:
    """Every other project in the workspace, as the inference may name it."""
    rows = (
        Project.objects.filter(tenant_id=project.tenant_id)
        .exclude(pk=project.pk)
        .values("pk", "name", "root_path", "full_path")
        .order_by("full_path", "root_path")
    )
    return tuple(
        RosterEntry(full_path=r["full_path"], path=r["root_path"], name=r["name"], project_id=r["pk"])
        for r in rows
    )


def excluded_paths(project: Project) -> tuple[str, ...]:
    """Directories inside the project that other projects on its repository
    own (a whole-repository project leaves its monorepo's apps to them)."""
    location = project.location
    return tuple(
        sorted(
            p
            for p in project.repository_projects().values_list("root_path", flat=True)
            if p and p != project.root_path and location.contains(p)
        )
    )


class RefreshProjectTopology:
    def __init__(
        self,
        *,
        inference: TopologyInference,
        snapshot_factory: Callable[[Project], RepositorySnapshot],
    ):
        self._inference = inference
        self._snapshot_factory = snapshot_factory

    def run(self, project: Project) -> InferenceSummary:
        tenant_id = project.tenant_id
        roster = workspace_roster(project)
        context = InferenceContext(
            project_name=project.name,
            full_path=project.full_path,
            root_path=project.root_path,
            excluded_paths=excluded_paths(project),
            discover=not project.root_path and not project.is_artifact,
            roster=roster,
            log=lambda m: logger.info("deps[%s]: %s", project.name, m),
        )

        topology = self._inference.infer(self._snapshot_factory(project), context)
        check_evidence(topology.evidence)  # raise before touching any table

        # The project itself joins the roster so a reference to it resolves
        # (and is dropped as a self-loop) instead of counting as unresolved.
        itself = RosterEntry(project.full_path, project.root_path, project.name, project.pk)
        resolved = resolve_topology(
            topology, roster + (itself,), this_repo=project.full_path, this_path=project.root_path
        )
        for target in resolved.unresolved:
            logger.info("deps[%s]: unresolved internal target %r", project.name, target)

        deps = [
            ProjectDependency(
                tenant_id=tenant_id, source=project, target_id=r.target.project_id, label=r.label
            )
            for r in resolved.internal
            if r.target.project_id is not None and r.target.project_id != project.pk
        ]
        # One row per (name, direction) / name: the database enforces it only
        # from the release after components are dropped, so dedupe here too.
        externals = _unique(
            (
                (e.name.lower(), e.direction),
                ExternalDependency(
                    tenant_id=tenant_id,
                    project=project,
                    name=e.name,
                    direction=e.direction,
                    url=e.url,
                    description=e.label,
                ),
            )
            for e in resolved.externals
        )
        infra = _unique(
            (
                i.name.lower(),
                InfrastructureComponent(
                    tenant_id=tenant_id, project=project, name=i.name, kind=i.kind, description=i.label
                ),
            )
            for i in resolved.infrastructure
        )

        with transaction.atomic():
            ProjectDependency.objects.filter(tenant_id=tenant_id, source=project).delete()
            ExternalDependency.objects.filter(tenant_id=tenant_id, project=project).delete()
            InfrastructureComponent.objects.filter(tenant_id=tenant_id, project=project).delete()
            ProjectDependency.objects.bulk_create(deps, ignore_conflicts=True)
            ExternalDependency.objects.bulk_create(externals, ignore_conflicts=True)
            InfrastructureComponent.objects.bulk_create(infra, ignore_conflicts=True)

            fields = ["technologies", "deps_evidence", "deps_status", "deps_analyzed_at", "deps_error"]
            project.technologies = list(topology.technologies)
            if context.discover:
                project.suggested_projects = [s.to_dict() for s in topology.suggestions]
                fields.append("suggested_projects")
            project.deps_evidence = list(topology.evidence.files_read[:MAX_EVIDENCE_FILES])
            project.deps_status = Project.DepsStatus.OK
            project.deps_analyzed_at = timezone.now()
            project.deps_error = ""
            project.save(update_fields=fields)

        summary = InferenceSummary(
            internal=len(deps),
            infrastructure=len(infra),
            providers=sum(1 for e in externals if e.direction != INBOUND),
            consumers=sum(1 for e in externals if e.direction == INBOUND),
            files_read=len(topology.evidence.files_read),
            suggestions=len(topology.suggestions) if context.discover else 0,
            unresolved=resolved.unresolved,
        )
        logger.info(
            "deps[%s]: %d internal, %d infra, %d providers, %d consumers, %d suggested "
            "(%d files read)",
            project.name,
            summary.internal,
            summary.infrastructure,
            summary.providers,
            summary.consumers,
            summary.suggestions,
            summary.files_read,
        )
        return summary


def _unique(keyed_rows) -> list:
    """The rows of ``(key, row)`` pairs, the first of each key only."""
    rows: dict = {}
    for key, row in keyed_rows:
        rows.setdefault(key, row)
    return list(rows.values())
