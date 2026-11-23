"""Builders for the read-only architecture diagrams (React Flow).

Two graphs are produced here:

* ``workspace_graph`` — stacks as nodes, stack-to-stack dependencies as edges
  (the dashboard).
* ``stack_graph`` — the projects inside one stack as nodes, with
  project-level edges. Edges that cross the stack boundary become peripheral
  nodes: other workspace projects that *consume* one of this stack's projects
  (public-facing surface), other workspace projects this stack *consumes*,
  and third-party apps this stack depends on.

Nodes are *projects*: a monorepo's apps and services appear individually once
each is added as a project at its root path.

``ProjectDependency`` / ``ExternalDependency`` are populated by the LLM agent
per project; **stack→stack edges are derived here at read time** by rolling up
project edges across each stack's membership (the ``StackDependency`` model
is reserved for future manual stack-level labels and is not read here).
"""

from collections import Counter, defaultdict

from django.db.models import Max, Q
from django.urls import reverse

from app.application import scoring
from app.application.naming import canonical_key
from app.application.project_health_counts import ProjectHealthCounts
from app.presentation.no_score_note import NoScoreNote
from app.domain.models import (
    ExternalDependency,
    InfrastructureComponent,
    Project,
    ProjectDependency,
    Stack,
    StandardExecution,
)
from app.domain.health import project_level

MAX_TECHNOLOGIES = 8


def _represented(commit_score, representation):
    """A project's commit score as its workspace reads it ("B" or "82", "F",
    "—"), with the colour it is painted in."""
    if commit_score is None:
        return representation.represent(None)
    return representation.represent(commit_score.value, failed=commit_score.failed)


def _project_issue(project, commit_score, representation):
    """One line of a stack's hover: a project that needs attention, as
    itself: its grade (and why it failed), why it has no score, or that it
    has none yet."""
    if NoScoreNote.text(commit_score):
        return "{} — {}".format(project.name, NoScoreNote.text(commit_score))
    if commit_score is None:
        return "{} — no score yet".format(project.name)
    represented = _represented(commit_score, representation).text
    return "{} — {}{}".format(project.name, represented, ": " + commit_score.reason if commit_score.failed and commit_score.reason else "")


def _score_issues(commit_score):
    """Why a project needs attention: the Required standard that failed it,
    else its standards that failed or errored (their own status, not
    their numbers), failures first."""
    if commit_score is None:
        return []
    if commit_score.failed:
        return [commit_score.reason]
    if NoScoreNote.text(commit_score):
        return [NoScoreNote.text(commit_score)]
    status_text = {StandardExecution.Status.FAILED: "failed", StandardExecution.Status.ERROR: "errored"}
    problems = sorted(
        (e for e in commit_score.executions.all() if e.status in status_text),
        key=lambda e: (e.status != StandardExecution.Status.FAILED, e.standard_name.lower()),
    )
    return ["{} — {}".format(e.standard_name, status_text[e.status]) for e in problems[:4]]


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
    """A project's tech labels: its languages (counted from its own files for
    a project inside a monorepo) plus the LLM-inferred tech. Deduped,
    first-seen order."""
    return _merge_tech(project.languages, project.technologies)


def _technologies(projects):
    """Aggregate tech across a stack's projects, most-common first."""
    counts = Counter()
    for project in projects:
        for tech in _project_technologies(project):
            counts[tech] += 1
    return [tech for tech, _ in counts.most_common(MAX_TECHNOLOGIES)]


def _analyzing(project):
    return project.deps_status in (Project.DepsStatus.PENDING, Project.DepsStatus.RUNNING)


# --- Workspace (dashboard) graph -------------------------------------------


def workspace_map_status(tenant):
    """When the map was last rebuilt — the newest successful refresh among the
    workspace's projects — and whether a refresh is queued or running now."""
    return map_status(Project.objects.filter(tenant=tenant))


def map_status(projects):
    """When the map of these projects was last rebuilt (their newest
    successful refresh) and whether a refresh is queued or running now."""
    return {
        "updated_at": projects.aggregate(latest=Max("deps_analyzed_at"))["latest"],
        "analyzing": projects.filter(
            deps_status__in=(Project.DepsStatus.PENDING, Project.DepsStatus.RUNNING)
        ).exists(),
    }


def _stacks_of_projects(stacks) -> dict:
    """{project id: {stack id as string}}; ``stacks`` should prefetch ``projects``."""
    project_stacks = defaultdict(set)
    for stack in stacks:
        for p in stack.projects.all():
            project_stacks[p.id].add(str(stack.id))
    return project_stacks


def stack_dependencies(tenant, stacks) -> dict:
    """Stack-to-stack dependencies, derived from project dependencies and
    stack membership: if project A (in stack X) depends on project B (in
    stack Y), then X depends on Y. As {(X id, Y id): {labels}}, ids as
    strings. ``stacks`` should prefetch ``projects``."""
    project_stacks = _stacks_of_projects(stacks)

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
    return edge_labels


def workspace_graph(tenant):
    stacks = list(Stack.objects.filter(tenant=tenant).prefetch_related("projects"))
    project_scores = scoring.project_scores(Project.objects.filter(tenant=tenant))
    representation = tenant.score_representation

    stack_nodes = []
    for stack in stacks:
        projects = list(stack.projects.all())
        # A stack is never one grade or colour: it shows how many of its
        # projects are failed, need attention (no grade included) or are
        # healthy.
        counts = ProjectHealthCounts.of(projects, project_scores)

        # Issues = the projects that need attention, each with its own grade,
        # so the hover says which project to look at.
        issues = [_project_issue(p, s, representation) for p, s in counts.attention]

        stack_nodes.append(
            {
                "id": str(stack.id),
                "name": stack.name,
                "description": stack.description,
                "project_count": len(projects),
                "technologies": _technologies(projects),
                "project_health": counts.as_dict(),
                "issues": issues,
                # True while any member project's dependency analysis is queued
                # or running — drives the "regenerating…" hint.
                "analyzing": any(_analyzing(p) for p in projects),
                "url": reverse("stack_detail", args=[stack.id]),
            }
        )

    project_stacks = _stacks_of_projects(stacks)
    edge_labels = stack_dependencies(tenant, stacks)

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
    # projects is. External nodes are deduped by name across the workspace.
    providers = {}
    consumers = {}
    seen_edges = set()
    ext = ExternalDependency.objects.filter(tenant=tenant).values(
        "project_id", "name", "url", "direction"
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
        for stack_id in project_stacks.get(e["project_id"], ()):
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


def _project_node(project, project_scores, representation):
    """A project in the stack diagram, scored by its own score
    (``app.application.scoring``). The stack's own score is computed apart."""
    commit_score = project_scores.get(project.id)
    score = commit_score.value if commit_score else None
    failed = bool(commit_score and commit_score.failed)
    return {
        "id": str(project.id),
        "name": project.name,
        "path": project.root_path,
        "kind": project.kind,
        "repository": project.full_path,
        # True for a project inside a monorepo, so the UI can badge the node
        # with its repository.
        "monorepo": bool(project.root_path),
        "lifecycle": project.get_lifecycle_display(),
        "technologies": _project_technologies(project)[:MAX_TECHNOLOGIES],
        "score": score,
        "score_text": _represented(commit_score, representation).text,
        "score_shade": _represented(commit_score, representation).shade,
        "health": project_level(score, failed=failed),
        "issues": _score_issues(commit_score),
        # Why there is no grade (no score, a standard errored or never ran):
        # the node shows a warning sign in its place, this on hover.
        "no_score": NoScoreNote.text(commit_score),
        "analyzing": _analyzing(project),
        "url": reverse("project_detail", args=[project.id]),
    }


def _boundary_node(node_id, project):
    """A workspace project outside this stack, shown at the boundary."""
    ext_stack = project.stacks.first()
    return {
        "id": node_id,
        "name": project.name,
        "repository": project.full_path if project.root_path else "",
        "stack_name": ext_stack.name if ext_stack else "",
        "url": reverse("stack_detail", args=[ext_stack.id])
        if ext_stack
        else reverse("project_detail", args=[project.id]),
    }


def stack_graph(stack):
    """Build the architecture graph for a single stack.

    Node kinds:
      * ``project``    — a project inside this stack (the diagram's core).
      * ``consumer``   — a workspace project (in another stack) that depends
                         on one of ours → our project is public-facing.
      * ``consuming``  — a workspace project (in another stack) that one of
                         our projects depends on.
      * ``thirdparty``    — an external service one of our projects depends on.
      * ``extconsumer``   — an external system that depends on one of our
                            projects (out-of-workspace consumer).

    Edge kinds: ``internal`` | ``public`` | ``consuming`` | ``thirdparty``.
    """
    tenant = stack.tenant
    internal = list(stack.projects.all())
    internal_ids = {p.id for p in internal}

    project_scores = scoring.project_scores(internal)
    projects = [_project_node(p, project_scores, tenant.score_representation) for p in internal]
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
            # Inbound: an outside project consumes ours → public-facing.
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
            # Outbound: our project consumes another workspace project.
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
    ext_deps = ExternalDependency.objects.filter(project__in=internal_ids)
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
                    "target": str(ext.project_id),
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
                    "source": str(ext.project_id),
                    "target": node_id,
                    "label": ext.description[:40] if ext.description else "",
                    "kind": "thirdparty",
                }
            )

    # Internal infrastructure (datastores/queues each project owns) —
    # rendered as internal nodes connected from their project. Per project,
    # so two services with their own Postgres are distinct nodes.
    infra = {}
    for ic in InfrastructureComponent.objects.filter(project__in=internal_ids):
        node_id = f"infra:{ic.project_id}:{ic.name.lower()}"
        infra.setdefault(
            node_id, {"id": node_id, "name": ic.name, "kind": ic.kind}
        )
        edges.append(
            {
                "id": str(ic.id),
                "source": str(ic.project_id),
                "target": node_id,
                "label": "",
                "kind": "internal",
            }
        )

    return {
        "projects": projects,
        "consumers": list(consumers.values()),
        "consuming": list(consuming.values()),
        "thirdparties": list(thirdparties.values()),
        "external_consumers": list(ext_consumers.values()),
        "infrastructure": list(infra.values()),
        "edges": edges,
    }
