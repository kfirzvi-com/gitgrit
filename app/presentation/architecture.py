"""Builders for the read-only architecture diagrams (React Flow).

Two graphs are produced here:

* ``workspace_graph`` — stacks as nodes, stack-to-stack dependencies as edges
  (the dashboard).
* ``stack_graph`` — the projects inside one stack as nodes, with project-level
  edges. Edges that cross the stack boundary become peripheral nodes: other
  workspace projects that *consume* one of this stack's projects (public-facing
  surface), other workspace projects this stack *consumes*, and third-party
  apps this stack depends on.

``ProjectDependency`` / ``ExternalDependency`` are populated by the LLM agent
per repo; **stack→stack edges are derived here at read time** by rolling up
project edges across each stack's project membership (the ``StackDependency``
model is reserved for future manual stack-level labels and is not read here).
"""

from collections import Counter, defaultdict

from django.db.models import Q
from django.urls import reverse

from app.domain.models import (
    ExternalDependency,
    PolicyExecution,
    Project,
    ProjectDependency,
    Stack,
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


def latest_scores_by_project(tenant):
    """Map each project to its latest result per policy.

    Returns ``{project_id: {policy_key: {"name", "score"}}}`` where
    ``policy_key`` is the policy id (or name, for deleted policies). The policy
    name is kept so health tooltips can name the specific policies dragging a
    project down.
    """
    executions = (
        PolicyExecution.objects.filter(project__tenant=tenant)
        .order_by("-created_at")
        .values("project_id", "policy_id", "policy_name", "score")
    )
    latest = defaultdict(dict)
    for ex in executions:
        key = ex["policy_id"] or ex["policy_name"]
        results = latest[ex["project_id"]]
        if key not in results:
            results[key] = {"name": ex["policy_name"], "score": ex["score"]}
    return latest


def _project_score(project_id, latest):
    results = latest.get(project_id, {})
    if not results:
        return None
    return round(sum(r["score"] for r in results.values()) / len(results))


def attention_items(tenant):
    """Current policy results that need attention, worst-first.

    The latest result per (project, policy) that is needs-attention/critical by
    score or failed/errored. Returns the full ranked list; the dashboard shows
    the top few and counts the rest. Each item links to its execution detail.
    """
    executions = (
        PolicyExecution.objects.filter(project__tenant=tenant)
        .select_related("project", "policy")
        .order_by("-created_at")[:500]
    )

    seen = set()
    items = []
    for ex in executions:
        key = (ex.project_id, ex.policy_id or ex.policy_name)
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
                "policy_name": ex.policy_name,
                "policy_url": (
                    reverse("policy_detail", args=[ex.policy_id])
                    if ex.policy_id
                    else ""
                ),
                "score": ex.score,
                "status": ex.get_status_display(),
                "url": reverse("policy_execution_detail", args=[ex.id]),
                "when": ex.created_at,
            }
        )

    rank = {CRITICAL: 2, WARNING: 1}
    items.sort(key=lambda i: (rank.get(i["level"], 0), i["when"]), reverse=True)
    return items


def _project_issues(project_id, latest):
    """Reasons a project needs attention — its lowest sub-threshold policies.

    Returns a list of short strings for the hover tooltip. Empty when the
    project is healthy or has no results. Future signals (DORA deployment
    frequency, failing high-severity policies) should append their own
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


def _project_technologies(project):
    """A project's tech labels: GitHub languages + LLM-inferred tech, deduped."""
    return _merge_tech(project.languages, project.inferred_technologies)


def _technologies(projects):
    """Aggregate tech across a stack's projects, most-common first."""
    counts = Counter()
    for project in projects:
        for tech in _project_technologies(project):
            counts[tech] += 1
    return [tech for tech, _ in counts.most_common(MAX_TECHNOLOGIES)]


# --- Workspace (dashboard) graph -------------------------------------------


def workspace_graph(tenant, latest):
    stacks = Stack.objects.filter(tenant=tenant).prefetch_related("projects")

    stack_nodes = []
    for stack in stacks:
        projects = list(stack.projects.all())
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
                "project_count": len(projects),
                "technologies": _technologies(projects),
                "score": score,
                # Worst-of across projects, so a single failing project lights
                # up the whole stack even when the average looks healthy.
                "health": stack_level([project_level(s) for s in scores]),
                "issues": issues,
                # True while any member project's dependency analysis is queued
                # or running — drives the "regenerating…" hint.
                "analyzing": any(
                    p.deps_status
                    in (Project.DepsStatus.PENDING, Project.DepsStatus.RUNNING)
                    for p in projects
                ),
                "url": reverse("stack_detail", args=[stack.id]),
            }
        )

    # Derive stack→stack edges from project dependencies + stack membership:
    # if project A (in stack X) depends on project B (in stack Y), then X→Y.
    project_stacks = defaultdict(set)
    for stack in stacks:
        for p in stack.projects.all():
            project_stacks[p.id].add(str(stack.id))

    edge_labels: dict[tuple[str, str], set] = defaultdict(set)
    for dep in ProjectDependency.objects.filter(tenant=tenant).values(
        "source_id", "target_id", "label"
    ):
        for src in project_stacks.get(dep["source_id"], ()):
            for tgt in project_stacks.get(dep["target_id"], ()):
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
        }
        for (src, tgt), labels in edge_labels.items()
    ]

    return {"stacks": stack_nodes, "dependencies": dependencies}


# --- Per-stack graph --------------------------------------------------------


def _project_node(project, latest):
    score = _project_score(project.id, latest)
    return {
        "id": str(project.id),
        "name": project.name,
        "lifecycle": project.get_lifecycle_display(),
        "technologies": _project_technologies(project)[:MAX_TECHNOLOGIES],
        "score": score,
        "health": project_level(score),
        "issues": _project_issues(project.id, latest),
        "analyzing": project.deps_status
        in (Project.DepsStatus.PENDING, Project.DepsStatus.RUNNING),
        "url": reverse("project_detail", args=[project.id]),
    }


def _first_stack(project):
    """A representative stack label for an out-of-stack workspace project."""
    stack = project.stacks.first()
    return stack


def stack_graph(stack, latest):
    """Build the architecture graph for a single stack.

    Node kinds:
      * ``project``    — a project inside this stack (the diagram's core).
      * ``consumer``   — a workspace project (in another stack) that depends on
                         one of our projects → our project is public-facing.
      * ``consuming``  — a workspace project (in another stack) that one of our
                         projects depends on.
      * ``thirdparty``    — an external service one of our projects depends on.
      * ``extconsumer``   — an external system that depends on one of our
                            projects (out-of-workspace consumer).

    Edge kinds: ``internal`` | ``public`` | ``consuming`` | ``thirdparty``.
    """
    tenant = stack.tenant
    internal = list(stack.projects.all())
    internal_ids = {p.id for p in internal}

    projects = [_project_node(p, latest) for p in internal]
    consumers = {}
    consuming = {}
    thirdparties = {}
    ext_consumers = {}
    edges = []

    # Project-to-project dependencies touching this stack.
    deps = (
        ProjectDependency.objects.filter(tenant=tenant)
        .filter(Q(source__in=internal_ids) | Q(target__in=internal_ids))
        .select_related("source", "target")
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
            # Inbound: an external project consumes ours → public-facing.
            ext = dep.source
            node_id = f"consumer:{ext.id}"
            ext_stack = _first_stack(ext)
            consumers.setdefault(
                node_id,
                {
                    "id": node_id,
                    "name": ext.name,
                    "stack_name": ext_stack.name if ext_stack else "",
                    "url": reverse("stack_detail", args=[ext_stack.id])
                    if ext_stack
                    else reverse("project_detail", args=[ext.id]),
                },
            )
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
            # Outbound: our project consumes another workspace project.
            ext = dep.target
            node_id = f"consuming:{ext.id}"
            ext_stack = _first_stack(ext)
            consuming.setdefault(
                node_id,
                {
                    "id": node_id,
                    "name": ext.name,
                    "stack_name": ext_stack.name if ext_stack else "",
                    "url": reverse("stack_detail", args=[ext_stack.id])
                    if ext_stack
                    else reverse("project_detail", args=[ext.id]),
                },
            )
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
    ext_deps = ExternalDependency.objects.filter(project__in=internal_ids)
    for ext in ext_deps:
        inbound = ext.direction == ExternalDependency.Direction.INBOUND
        if inbound:
            node_id = f"extconsumer:{ext.name.lower()}"
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
                    "target": str(ext.project_id),
                    "label": ext.description[:40] if ext.description else "",
                    "kind": "public",
                }
            )
        else:
            node_id = f"thirdparty:{ext.name.lower()}"
            thirdparties.setdefault(
                node_id, {"id": node_id, "name": ext.name, "url": ext.url}
            )
            edges.append(
                {
                    "id": str(ext.id),
                    "source": str(ext.project_id),
                    "target": node_id,
                    "label": ext.description[:40] if ext.description else "",
                    "kind": "thirdparty",
                }
            )

    return {
        "projects": projects,
        "consumers": list(consumers.values()),
        "consuming": list(consuming.values()),
        "thirdparties": list(thirdparties.values()),
        "external_consumers": list(ext_consumers.values()),
        "edges": edges,
    }
