"""Refresh one project's components and dependency edges.

The single write path for the architecture graph. Given an inference (LLM,
fixture, …) and a way to snapshot the repository, it:

1. reads the repository's own map file (``.gitgrit.yml``) — when it declares
   everything the map is built from it with no model call; otherwise it
   infers a ``RepositoryTopology``, and the inference skips what the file
   declares (no file: the model maps the whole repository);
2. refuses one that was never grounded in the repository (evidence gate) so
   the previous map survives a bad run;
3. resolves the topology's names against the workspace roster;
4. in one transaction, reconciles the project's components by path (stable
   ids; memberships inherited on shape change) and replaces its edges,
   externals and infrastructure;
5. after commit, queues a refresh for other projects whose edges pointed at a
   component that no longer exists.

Stack-to-stack edges are NOT written here; they are derived at read time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Callable

from django.db import transaction
from django.utils import timezone

from app.application.architecture.ports import (
    InferenceContext,
    RepositorySnapshot,
    TopologyInference,
)
from app.domain.architecture.map_file import (
    MAP_FILE_NAMES,
    MapFile,
    MapFileError,
    declared_topology,
    parse_map_file,
)
from app.domain.architecture.reconcile import inherited_memberships, plan_components
from app.domain.architecture.resolve import RosterEntry, resolve_topology
from app.domain.architecture.topology import (
    INBOUND,
    MAX_EVIDENCE_FILES,
    RepositoryTopology,
    check_evidence,
)
from app.domain.models import (
    Component,
    ComponentDependency,
    ComponentStack,
    ExternalDependency,
    InfrastructureComponent,
    Project,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceSummary:
    components: int
    internal: int
    infrastructure: int
    providers: int
    consumers: int
    files_read: int
    created: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()

    @property
    def external(self) -> int:
        return self.providers + self.consumers


def workspace_roster(project: Project) -> tuple[RosterEntry, ...]:
    """Every component in the workspace outside this project."""
    rows = (
        Component.objects.filter(tenant_id=project.tenant_id)
        .exclude(project=project)
        .values("pk", "name", "path", "project__full_path")
        .order_by("project__full_path", "path")
    )
    return tuple(
        RosterEntry(
            full_path=r["project__full_path"], path=r["path"], name=r["name"], component_id=r["pk"]
        )
        for r in rows
    )


def read_map_file(snapshot: RepositorySnapshot, tree: list[str], log) -> MapFile:
    """The repository's root ``.gitgrit.yml``, or an empty ``MapFile`` when
    there is none or it is unusable (logged; the model then maps everything)."""
    path = next((n for n in MAP_FILE_NAMES if n in tree), None)
    if path is None:
        return MapFile()
    try:
        map_file = parse_map_file(snapshot.read_file(path) or "", path)
    except MapFileError as exc:
        log(f"{path} ignored: {exc}")
        return MapFile()
    for warning in map_file.warnings:
        log(f"{path}: {warning}")
    return map_file


class RefreshProjectTopology:
    def __init__(
        self,
        *,
        inference: TopologyInference,
        snapshot_factory: Callable[[Project], RepositorySnapshot],
        enqueue_refresh: Callable[[str], None] | None = None,
    ):
        self._inference = inference
        self._snapshot_factory = snapshot_factory
        self._enqueue_refresh = enqueue_refresh

    def run(self, project: Project) -> InferenceSummary:
        tenant_id = project.tenant_id
        roster = workspace_roster(project)
        context = InferenceContext(
            project_name=project.name,
            full_path=project.full_path,
            roster=roster,
            log=lambda m: logger.info("deps[%s]: %s", project.name, m),
        )

        snapshot = self._snapshot_factory(project)
        tree = snapshot.list_files() or []
        map_file = read_map_file(snapshot, tree, context.log)
        topology = declared_topology(map_file, tree, project.name)
        if topology is not None:
            context.log(f"mapped from {map_file.path}; no model call")
        else:
            topology = self._inference.infer(snapshot, replace(context, map_file=map_file))
        check_evidence(topology.evidence)  # raise before touching any table

        # Siblings discovered in this run join the roster without ids; they are
        # looked up by path once the components are persisted.
        full_roster = roster + tuple(
            RosterEntry(full_path=project.full_path, path=c.path, name=c.name)
            for c in topology.components
        )
        resolved = resolve_topology(topology, full_roster, this_repo=project.full_path)
        for target in resolved.unresolved:
            logger.info("deps[%s]: unresolved internal target %r", project.name, target)

        with transaction.atomic():
            components, plan, affected = self._reconcile_components(project, topology)
            by_path = {c.path: c for c in components}

            def component_for(entry: RosterEntry):
                if entry.component_id is not None:
                    return entry.component_id
                return by_path[entry.path].pk  # a sibling created above

            deps = [
                ComponentDependency(
                    tenant_id=tenant_id,
                    source=by_path[r.source_path],
                    target_id=component_for(r.target),
                    label=r.label,
                )
                for r in resolved.internal
            ]
            deps = [d for d in deps if d.source_id != d.target_id]
            externals = [
                ExternalDependency(
                    tenant_id=tenant_id,
                    component=by_path[e.source_path],
                    name=e.name,
                    direction=e.direction,
                    url=e.url,
                    description=e.label,
                )
                for e in resolved.externals
            ]
            infra = [
                InfrastructureComponent(
                    tenant_id=tenant_id,
                    component=by_path[i.source_path],
                    name=i.name,
                    kind=i.kind,
                    description=i.label,
                )
                for i in resolved.infrastructure
            ]

            ComponentDependency.objects.filter(tenant_id=tenant_id, source__project=project).delete()
            ExternalDependency.objects.filter(tenant_id=tenant_id, component__project=project).delete()
            InfrastructureComponent.objects.filter(
                tenant_id=tenant_id, component__project=project
            ).delete()
            ComponentDependency.objects.bulk_create(deps, ignore_conflicts=True)
            ExternalDependency.objects.bulk_create(externals, ignore_conflicts=True)
            InfrastructureComponent.objects.bulk_create(infra, ignore_conflicts=True)

            evidence = topology.evidence
            read = ([evidence.map_file] if evidence.map_file else []) + list(evidence.files_read)
            project.deps_evidence = read[:MAX_EVIDENCE_FILES]
            project.deps_status = Project.DepsStatus.OK
            project.deps_analyzed_at = timezone.now()
            project.deps_error = ""
            project.save(
                update_fields=["deps_evidence", "deps_status", "deps_analyzed_at", "deps_error"]
            )

            if affected and self._enqueue_refresh is not None:
                enqueue = self._enqueue_refresh
                transaction.on_commit(lambda: [enqueue(str(pk)) for pk in affected])

        summary = InferenceSummary(
            components=len(components),
            internal=len(deps),
            infrastructure=len(infra),
            providers=sum(1 for e in externals if e.direction != INBOUND),
            consumers=sum(1 for e in externals if e.direction == INBOUND),
            files_read=len(topology.evidence.files_read),
            created=plan.create,
            removed=plan.remove,
            unresolved=resolved.unresolved,
        )
        logger.info(
            "deps[%s]: %d components (+%d/-%d), %d internal, %d infra, %d providers, "
            "%d consumers (%d files read)",
            project.name,
            summary.components,
            len(plan.create),
            len(plan.remove),
            summary.internal,
            summary.infrastructure,
            summary.providers,
            summary.consumers,
            summary.files_read,
        )
        return summary

    def _reconcile_components(self, project: Project, topology: RepositoryTopology):
        """Apply the reconcile plan inside the caller's transaction. Returns the
        project's components after the change, the plan, and the ids of other
        projects whose edges into removed components were cascaded."""
        existing = {c.path: c for c in project.components.all()}
        decls = {c.path: c for c in topology.components}
        plan = plan_components(existing.keys(), decls.keys())

        memberships: dict[str, set] = {}
        for row in ComponentStack.objects.filter(
            component__project=project, component__path__in=plan.remove
        ).values("component__path", "stack_id"):
            memberships.setdefault(row["component__path"], set()).add(row["stack_id"])
        inherited = inherited_memberships(plan, memberships)

        removed_ids = [existing[p].pk for p in plan.remove]
        affected = set(
            ComponentDependency.objects.filter(target_id__in=removed_ids)
            .exclude(source__project=project)
            .values_list("source__project_id", flat=True)
        )

        components: list[Component] = []
        for path in plan.keep:
            component, decl = existing[path], decls[path]
            component.name = project.name if path == "" else decl.name
            component.kind = decl.kind
            component.description = decl.description
            component.technologies = list(decl.technologies)
            component.save(update_fields=["name", "kind", "description", "technologies", "updated_at"])
            components.append(component)
        for path in plan.create:
            decl = decls[path]
            components.append(
                Component.objects.create(
                    tenant_id=project.tenant_id,
                    project=project,
                    path=path,
                    name=project.name if path == "" else decl.name,
                    kind=decl.kind,
                    description=decl.description,
                    technologies=list(decl.technologies),
                )
            )
        by_path = {c.path: c for c in components}
        ComponentStack.objects.bulk_create(
            [
                ComponentStack(component=by_path[path], stack_id=stack_id)
                for path, stack_ids in inherited.items()
                for stack_id in stack_ids
            ],
            ignore_conflicts=True,
        )
        if removed_ids:
            Component.objects.filter(pk__in=removed_ids).delete()  # cascades edges + memberships

        return components, plan, affected
