"""Builders for the read-only architecture diagrams (React Flow).

Two graphs are produced here:

* ``workspace_graph`` — stacks as nodes, stack-to-stack dependencies as edges
  (the dashboard).
* ``stack_graph`` — the components inside one stack as nodes, with
  component-level edges. Edges that cross the stack boundary become peripheral
  nodes: other workspace components that *consume* one of this stack's
  components (public-facing surface), other workspace components this stack
  *consumes*, and third-party apps this stack depends on.

Nodes are *components* (the deployable units inside a repository), so a
monorepo's services appear individually and a plain repository appears as its
single root component. Health is still scored per project (standards run per
repository), so every component of a repository shares its project's colour.

``ComponentDependency`` / ``ExternalDependency`` are populated by the LLM agent
per repo; **stack→stack edges are derived here at read time** by rolling up
component edges across each stack's membership (the ``StackDependency`` model
is reserved for future manual stack-level labels and is not read here).
"""

from collections import Counter, defaultdict

from django.db.models import Count, Max, Q
from django.urls import reverse

from app.application import scoring
from app.domain.score_representation import COMMIT_SCORE_REPRESENTATION
from app.application.naming import canonical_key
from app.application.project_health_counts import ProjectHealthCounts
from app.domain.models import (
    ComponentDependency,
    ExternalDependency,
    InfrastructureComponent,
    Project,
    Stack,
    StandardExecution,
)
from app.domain.health import project_level

MAX_TECHNOLOGIES = 8


def _grade(commit_score):
    """A project's grade as the app shows it ("B", "F", "—")."""
    if commit_score is None:
        return _score_text(None)
    return _score_text(commit_score.value, failed=commit_score.failed)


def _component_issues(commit_score):
    """Why a project needs attention: the Required standard that failed it,
    else its standards that failed or could not run (their own status, not
    their numbers), failures first."""
    if commit_score is None:
        return []
    if commit_score.failed:
        return [commit_score.reason]
    status_text = {StandardExecution.Status.FAILED: "failed", StandardExecution.Status.ERROR: "could not run"}
    problems = sorted(
        (e for e in commit_score.executions.all() if e.status in status_text),
        key=lambda e: (e.status != StandardExecution.Status.FAILED, e.standard_name.lower()),
    )
    return ["{} — {}".format(e.standard_name, status_text[e.status]) for e in problems[:4]]


def _grade_shade(commit_score):
    """The colour a project's grade is painted in (orange for a D)."""
    if commit_score is None:
        return COMMIT_SCORE_REPRESENTATION.represent(None).shade
    return COMMIT_SCORE_REPRESENTATION.represent(commit_score.value, failed=commit_score.failed).shade


def _score_text(value, failed: bool = False):
    """A commit score as ``COMMIT_SCORE_REPRESENTATION`` shows it, for the diagrams."""
    return COMMIT_SCORE_REPRESENTATION.represent(value, failed=failed).text


def _merge_tech(*lists):
    """Merge tech lists, case-insensitively deduped, preserving first-seen order."""
    seen = set()
    out = []
    for lst in lists:
        for t in lst or []:
            t = (t or "").strip()
            key = t.lower()
            if t and key not in seen:
                seen.add(key)
                out.append(t)
    return out


def _component_technologies(component):
    """A component's tech labels: LLM-inferred tech plus, for a root component,
    the repository's GitHub languages (repo-wide languages would mislabel one
    service of a monorepo). Deduped, first-seen order."""
    languages = component.project.languages if component.is_root else []
    return _merge_tech(languages, component.technologies)


def _technologies(components):
    """Aggregate tech across a stack's components, most-common first."""
    counts = Counter()
    for component in components:
        for tech in _component_technologies(component):
            counts[tech] += 1
    return [tech for tech, _ in counts.most_common(MAX_TECHNOLOGIES)]


def _analyzing(project):
    return project.deps_status in (Project.DepsStatus.PENDING, Project.DepsStatus.RUNNING)


# --- Workspace (dashboard) graph -------------------------------------------


def workspace_map_status(tenant):
    """When the map was last rebuilt — the newest successful refresh among the
    workspace's projects — and whether a refresh is queued or running now."""
    projects = Project.objects.filter(tenant=tenant)
    return {
        "updated_at": projects.aggregate(latest=Max("deps_analyzed_at"))["latest"],
        "analyzing": projects.filter(
            deps_status__in=(Project.DepsStatus.PENDING, Project.DepsStatus.RUNNING)
        ).exists(),
    }


def workspace_graph(tenant):
    stacks = Stack.objects.filter(tenant=tenant).prefetch_related("components__project")
    project_scores = scoring.project_scores(Project.objects.filter(tenant=tenant))

    stack_nodes = []
    for stack in stacks:
        components = list(stack.components.all())
        # Health is per repository: score each distinct project once, however
        # many of its components sit in this stack.
        projects = list({c.project_id: c.project for c in components}.values())
        # A stack is never one grade or colour: it shows how many of its
        # projects are failed, need attention, are healthy or have no data.
        counts = ProjectHealthCounts.of(projects, project_scores)

        # Issues = the projects that need attention, each with its own grade,
        # so the hover says which project to look at.
        issues = [
            "{} — {}{}".format(p.name, _grade(s), ": " + s.reason if s.failed and s.reason else "")
            for p, s in counts.attention
        ]

        stack_nodes.append(
            {
                "id": str(stack.id),
                "name": stack.name,
                "description": stack.description,
                "component_count": len(components),
                "project_count": len(projects),
                "technologies": _technologies(components),
                "project_health": counts.as_dict(),
                "issues": issues,
                # True while any member project's dependency analysis is queued
                # or running — drives the "regenerating…" hint.
                "analyzing": any(_analyzing(p) for p in projects),
                "url": reverse("stack_detail", args=[stack.id]),
            }
        )

    # Derive stack→stack edges from component dependencies + stack membership:
    # if component A (in stack X) depends on component B (in stack Y), then X→Y.
    component_stacks = defaultdict(set)
    for stack in stacks:
        for c in stack.components.all():
            component_stacks[c.id].add(str(stack.id))

    edge_labels: dict[tuple[str, str], set] = defaultdict(set)
    for dep in ComponentDependency.objects.filter(tenant=tenant).values(
        "source_id", "target_id", "label"
    ):
        for src in component_stacks.get(dep["source_id"], ()):
            for tgt in component_stacks.get(dep["target_id"], ()):
                if src != tgt:
                    if dep["label"]:
                        edge_labels[(src, tgt)].add(dep["label"])
                    else:
                        edge_labels.setdefault((src, tgt), set())

    dependencies = [
        {
            "id": f"{src}->{tgt}",
            "source": src,
            "target": tgt,
            "label": ", ".join(sorted(labels))[:255],
            "kind": "workspace",
        }
        for (src, tgt), labels in edge_labels.items()
    ]

    # Aggregate external services to the stack level: a stack depends on a
    # provider (bottom) / is consumed by an external system (top) if any of its
    # components is. External nodes are deduped by name across the workspace.
    providers = {}
    consumers = {}
    seen_edges = set()
    ext = ExternalDependency.objects.filter(tenant=tenant).values(
        "component_id", "name", "url", "direction"
    )
    for e in ext:
        inbound = e["direction"] == ExternalDependency.Direction.INBOUND
        bucket = consumers if inbound else providers
        node_id = ("extconsumer:" if inbound else "extprovider:") + canonical_key(e["name"])
        existing = bucket.get(node_id)
        if existing is None:
            node = {"id": node_id, "name": e["name"], "url": e["url"]}
            if inbound:
                node["stack_name"] = "External"
            bucket[node_id] = node
        else:
            # Same service named differently across repos — keep the shortest.
            if len(e["name"]) < len(existing["name"]):
                existing["name"] = e["name"]
            if not existing.get("url") and e["url"]:
                existing["url"] = e["url"]
        for stack_id in component_stacks.get(e["component_id"], ()):
            if inbound:
                pair, kind = (node_id, stack_id), "public"
            else:
                pair, kind = (stack_id, node_id), "thirdparty"
            if pair in seen_edges:
                continue
            seen_edges.add(pair)
            dependencies.append(
                {"id": f"{pair[0]}->{pair[1]}", "source": pair[0], "target": pair[1],
                 "label": "", "kind": kind}
            )

    return {
        "stacks": stack_nodes,
        "external_providers": list(providers.values()),
        "external_consumers": list(consumers.values()),
        "dependencies": dependencies,
    }


# --- Per-stack graph --------------------------------------------------------


def _component_node(component, monorepo_projects, project_scores):
    """A component in the stack diagram, scored by its project's score
    (``app.application.scoring``). The stack's own score is computed apart."""
    project = component.project
    commit_score = project_scores.get(project.id)
    score = commit_score.value if commit_score else None
    failed = bool(commit_score and commit_score.failed)
    return {
        "id": str(component.id),
        "name": component.name,
        "path": component.path,
        "kind": component.kind,
        "project_id": str(project.id),
        "project_name": project.name,
        "project_url": reverse("project_detail", args=[project.id]),
        # True when the repository holds other components too, so the UI can
        # badge the node with its repository.
        "monorepo": project.id in monorepo_projects,
        "lifecycle": project.get_lifecycle_display(),
        "technologies": _component_technologies(component)[:MAX_TECHNOLOGIES],
        "score": score,
        "score_text": _score_text(score, failed=failed),
        "score_shade": _grade_shade(commit_score),
        "health": project_level(score, failed=failed),
        "issues": _component_issues(commit_score),
        "analyzing": _analyzing(project),
        "url": reverse("project_detail", args=[project.id]),
    }


def _first_stack(component):
    """A representative stack label for an out-of-stack workspace component."""
    return component.stacks.first()


def _boundary_node(node_id, component):
    """A workspace component outside this stack, shown at the boundary."""
    ext_stack = _first_stack(component)
    return {
        "id": node_id,
        "name": component.name,
        "project_name": component.project.name,
        "stack_name": ext_stack.name if ext_stack else "",
        "url": reverse("stack_detail", args=[ext_stack.id])
        if ext_stack
        else reverse("project_detail", args=[component.project_id]),
    }


def stack_graph(stack):
    """Build the architecture graph for a single stack.

    Node kinds:
      * ``component``  — a component inside this stack (the diagram's core).
      * ``consumer``   — a workspace component (in another stack) that depends
                         on one of ours → our component is public-facing.
      * ``consuming``  — a workspace component (in another stack) that one of
                         our components depends on.
      * ``thirdparty``    — an external service one of our components depends on.
      * ``extconsumer``   — an external system that depends on one of our
                            components (out-of-workspace consumer).

    Edge kinds: ``internal`` | ``public`` | ``consuming`` | ``thirdparty``.
    """
    tenant = stack.tenant
    internal = list(stack.components.select_related("project"))
    internal_ids = {c.id for c in internal}
    monorepo_projects = {
        p_id
        for p_id, n in Counter(c.project_id for c in internal).items()
        if n > 1
    } | set(
        Project.objects.filter(pk__in={c.project_id for c in internal})
        .annotate(n=Count("components"))
        .filter(n__gt=1)
        .values_list("pk", flat=True)
    )

    project_scores = scoring.project_scores({c.project for c in internal})
    components = [
        _component_node(c, monorepo_projects, project_scores) for c in internal
    ]
    consumers = {}
    consuming = {}
    thirdparties = {}
    ext_consumers = {}
    edges = []

    # Component-to-component dependencies touching this stack.
    deps = (
        ComponentDependency.objects.filter(tenant=tenant)
        .filter(Q(source__in=internal_ids) | Q(target__in=internal_ids))
        .select_related("source__project", "target__project")
    )
    for dep in deps:
        s_in = dep.source_id in internal_ids
        t_in = dep.target_id in internal_ids

        if s_in and t_in:
            edges.append(
                {
                    "id": str(dep.id),
                    "source": str(dep.source_id),
                    "target": str(dep.target_id),
                    "label": dep.label,
                    "kind": "internal",
                }
            )
        elif t_in and not s_in:
            # Inbound: an outside component consumes ours → public-facing.
            node_id = f"consumer:{dep.source_id}"
            consumers.setdefault(node_id, _boundary_node(node_id, dep.source))
            edges.append(
                {
                    "id": str(dep.id),
                    "source": node_id,
                    "target": str(dep.target_id),
                    "label": dep.label,
                    "kind": "public",
                }
            )
        elif s_in and not t_in:
            # Outbound: our component consumes another workspace component.
            node_id = f"consuming:{dep.target_id}"
            consuming.setdefault(node_id, _boundary_node(node_id, dep.target))
            edges.append(
                {
                    "id": str(dep.id),
                    "source": str(dep.source_id),
                    "target": node_id,
                    "label": dep.label,
                    "kind": "consuming",
                }
            )

    # External (out-of-workspace) relationships, deduped by app name. Outbound
    # = providers we depend on (bottom); inbound = consumers that depend on us
    # (top, edge kind "public" so it reads like our other public-facing edges).
    ext_deps = ExternalDependency.objects.filter(component__in=internal_ids)
    for ext in ext_deps:
        inbound = ext.direction == ExternalDependency.Direction.INBOUND
        if inbound:
            node_id = f"extconsumer:{canonical_key(ext.name)}"
            ext_consumers.setdefault(
                node_id,
                {
                    "id": node_id,
                    "name": ext.name,
                    "stack_name": "External",
                    "url": ext.url,
                },
            )
            edges.append(
                {
                    "id": str(ext.id),
                    "source": node_id,
                    "target": str(ext.component_id),
                    "label": ext.description[:40] if ext.description else "",
                    "kind": "public",
                }
            )
        else:
            node_id = f"thirdparty:{canonical_key(ext.name)}"
            thirdparties.setdefault(
                node_id, {"id": node_id, "name": ext.name, "url": ext.url}
            )
            edges.append(
                {
                    "id": str(ext.id),
                    "source": str(ext.component_id),
                    "target": node_id,
                    "label": ext.description[:40] if ext.description else "",
                    "kind": "thirdparty",
                }
            )

    # Internal infrastructure (datastores/queues each component owns) —
    # rendered as internal nodes connected from their component. Per-component,
    # so two services with their own Postgres are distinct nodes.
    infra = {}
    for ic in InfrastructureComponent.objects.filter(component__in=internal_ids):
        node_id = f"infra:{ic.component_id}:{ic.name.lower()}"
        infra.setdefault(
            node_id, {"id": node_id, "name": ic.name, "kind": ic.kind}
        )
        edges.append(
            {
                "id": str(ic.id),
                "source": str(ic.component_id),
                "target": node_id,
                "label": "",
                "kind": "internal",
            }
        )

    return {
        "components": components,
        "consumers": list(consumers.values()),
        "consuming": list(consuming.values()),
        "thirdparties": list(thirdparties.values()),
        "external_consumers": list(ext_consumers.values()),
        "infrastructure": list(infra.values()),
        "edges": edges,
    }
