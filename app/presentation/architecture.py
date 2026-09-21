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

from django.db.models import Count, Exists, OuterRef, Q
from django.urls import reverse

from app.application.naming import canonical_key
from app.domain.models import (
    ComponentDependency,
    ExternalDependency,
    InfrastructureComponent,
    Project,
    ProjectStandard,
    Stack,
    StandardExecution,
)
from app.presentation.health import (
    CRITICAL,
    HEALTHY,
    HEALTHY_MIN,
    WARNING,
    level_from_score,
    project_level,
    stack_level,
)

MAX_TECHNOLOGIES = 8


def _attached_executions(tenant):
    """Tenant executions whose standard is currently attached to their project.

    Detached (or deleted) standards' old executions must not drag project
    scores or raise attention items, so every dashboard read starts here.
    """
    attached = ProjectStandard.objects.filter(
        project_id=OuterRef("project_id"), standard_id=OuterRef("standard_id")
    )
    return StandardExecution.objects.filter(
        Exists(attached), project__tenant=tenant
    )


def latest_scores_by_project(tenant):
    """Map each attached project/standard pair to its latest result.

    Returns ``{project_id: {standard_id: {"name", "score"}}}``. The standard
    name is kept so health tooltips can name the specific standards dragging a
    project down. In-flight (RUNNING) executions are excluded — they score 0
    until the worker finishes them, which would read as a regression.
    """
    executions = (
        _attached_executions(tenant)
        .exclude(status=StandardExecution.Status.RUNNING)
        .order_by("-created_at")
        .values("project_id", "standard_id", "standard_name", "score")
    )
    latest = defaultdict(dict)
    for ex in executions:
        results = latest[ex["project_id"]]
        if ex["standard_id"] not in results:
            results[ex["standard_id"]] = {
                "name": ex["standard_name"],
                "score": ex["score"],
            }
    return latest


def _project_score(project_id, latest):
    results = latest.get(project_id, {})
    if not results:
        return None
    return round(sum(r["score"] for r in results.values()) / len(results))


def attention_items(tenant):
    """Current standard results that need attention, worst-first.

    The latest result per (project, standard) that is needs-attention/critical by
    score or failed/errored. Returns the full ranked list; the dashboard shows
    the top few and counts the rest. Each item links to its execution detail.
    """
    # In-flight rows score 0 until the worker finishes them; they would show
    # as critical and hide the real latest result for that pair.
    executions = (
        _attached_executions(tenant)
        .exclude(status=StandardExecution.Status.RUNNING)
        .select_related("project", "standard")
        .order_by("-created_at")[:500]
    )

    seen = set()
    items = []
    for ex in executions:
        key = (ex.project_id, ex.standard_id)
        if key in seen:
            continue
        seen.add(key)

        level = level_from_score(ex.score)
        failed = ex.status in ("failed", "error")
        if level == HEALTHY and not failed:
            continue
        if level == HEALTHY:  # failed/errored but scored OK — still flag it
            level = WARNING

        items.append(
            {
                "level": level,
                "project_name": ex.project.name,
                "project_url": reverse("project_detail", args=[ex.project_id]),
                "standard_name": ex.standard_name,
                "standard_url": reverse("standard_detail", args=[ex.standard_id]),
                "score": ex.score,
                "status": ex.get_status_display(),
                "url": reverse("standard_execution_detail", args=[ex.id]),
                "when": ex.created_at,
            }
        )

    rank = {CRITICAL: 2, WARNING: 1}
    items.sort(key=lambda i: (rank.get(i["level"], 0), i["when"]), reverse=True)
    return items


def _project_issues(project_id, latest):
    """Reasons a project needs attention — its lowest sub-threshold standards.

    Returns a list of short strings for the hover tooltip. Empty when the
    project is healthy or has no results. Future signals (DORA deployment
    frequency, failing high-severity standards) should append their own
    reasons here so the tooltip stays the single explanation of node health.
    """
    results = latest.get(project_id, {})
    low = sorted(
        (r for r in results.values() if r["score"] < HEALTHY_MIN),
        key=lambda r: r["score"],
    )
    return ["{} — {}%".format(r["name"], r["score"]) for r in low[:4]]


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


def workspace_graph(tenant, latest):
    stacks = Stack.objects.filter(tenant=tenant).prefetch_related("components__project")

    stack_nodes = []
    for stack in stacks:
        components = list(stack.components.all())
        # Health is per repository: score each distinct project once, however
        # many of its components sit in this stack.
        projects = list({c.project_id: c.project for c in components}.values())
        scores = [_project_score(p.id, latest) for p in projects]
        known = [s for s in scores if s is not None]
        score = round(sum(known) / len(known)) if known else None

        # Issues = the projects dragging the stack down (worst first), so the
        # hover explains which project to look at.
        offenders = sorted(
            (
                (p, s, project_level(s))
                for p, s in zip(projects, scores)
            ),
            key=lambda t: (t[1] if t[1] is not None else 999),
        )
        issues = [
            "{} — {}% ({})".format(p.name, s, lvl)
            for p, s, lvl in offenders
            if lvl in (WARNING, CRITICAL)
        ]

        stack_nodes.append(
            {
                "id": str(stack.id),
                "name": stack.name,
                "description": stack.description,
                "component_count": len(components),
                "project_count": len(projects),
                "technologies": _technologies(components),
                "score": score,
                # Worst-of across projects, so a single failing project lights
                # up the whole stack even when the average looks healthy.
                "health": stack_level([project_level(s) for s in scores]),
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


def _component_node(component, latest, monorepo_projects):
    project = component.project
    score = _project_score(project.id, latest)
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
        "health": project_level(score),
        "issues": _project_issues(project.id, latest),
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


def stack_graph(stack, latest):
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

    components = [_component_node(c, latest, monorepo_projects) for c in internal]
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
