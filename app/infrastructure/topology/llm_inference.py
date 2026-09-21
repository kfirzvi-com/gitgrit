"""LLM-backed ``TopologyInference``: two runs of the in-process agent.

**Phase 1 — discovery.** The model lists the repository and names its
components (the independently deployable/publishable units). A plain
single-application repository yields exactly one, the root.

**Phase 2 — dependencies, per component.** For each component the model gets
a toolbox whose default listing is scoped to that component's directory
(``read_file`` stays repository-wide so root manifests remain readable) and
returns the component's internal, infrastructure and external dependencies
plus its tech labels.

Two phases rather than one nested answer because ``LLMAgent.run`` caps each
run at ``MAX_ITERATIONS`` / ``MAX_TOOL_CALLS``: an eight-component monorepo
needs a few reads per component, which no single run could afford. A
root-only repository costs one discovery run plus one dependency run.
"""
from __future__ import annotations

from dataclasses import replace

from pydantic import BaseModel, Field

from app.application.architecture.ports import InferenceContext, RepositorySnapshot
from app.domain.architecture.resolve import RosterEntry
from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    ComponentDecl,
    Evidence,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    RepositoryTopology,
    clean_technologies,
    normalise_components,
)
from app.infrastructure.llm_agent import LLMAgent
from app.infrastructure.topology.toolbox import RepoToolbox

ROLE = "reasoning"


# --- Phase 1: component discovery ------------------------------------------------

_DISCOVERY_PROMPT = (
    "You are identifying the COMPONENTS of one software repository for an "
    "architecture diagram: the independently deployable or publishable units "
    "it contains — services/APIs, frontends/apps, shared libraries, jobs and "
    "pipelines, infrastructure-as-code roots. Use the tools to look at the "
    "repository yourself.\n"
    "Evidence that a repository holds SEVERAL components: workspace manifests "
    "(package.json `workspaces`, pnpm-workspace.yaml, turbo.json, nx.json, "
    "lerna.json, `[tool.uv.workspace]` / Poetry workspaces in pyproject.toml, "
    "go.work, a Cargo workspace), docker-compose `build:` contexts pointing at "
    "sub-directories, per-directory Dockerfiles or manifests, CODEOWNERS, a "
    "README that lists the parts, conventional folders such as apps/, "
    "services/, packages/, libs/, infra/.\n"
    "A repository with ONE manifest at its root and no such evidence is ONE "
    "component at path '' (the repository root) — this is the common case; do "
    "not invent sub-components for ordinary folders like src/, tests/, docs/.\n"
    "Do not list every folder: list units that are built, deployed or "
    "published on their own. Give each a repository-relative directory path, "
    "a short name (usually the directory name or the manifest's package name), "
    "a kind (service | frontend | library | job | infra | other), a one-line "
    "description, and the languages/frameworks you can see in its manifest. "
    "Return at most 25 components. When you have enough evidence, stop calling "
    "tools and return the structured result."
)


class _ComponentDecl(BaseModel):
    path: str = Field(description="repository-relative directory, '' for the repository root")
    name: str = Field(default="", description="short component name")
    kind: str = Field(default="other", description="service | frontend | library | job | infra | other")
    description: str = Field(default="", description="one line: what this component is")
    technologies: list[str] = Field(default=[], description="languages/frameworks seen in its manifest")


class ComponentDiscovery(BaseModel):
    components: list[_ComponentDecl] = []


# --- Phase 2: dependencies of one component -----------------------------------------

_DEPENDENCY_PROMPT = (
    "You are mapping the dependencies of one software COMPONENT (a deployable "
    "unit inside a repository) for an architecture diagram. Use the tools to "
    "inspect it yourself: list files and read the ones that reveal dependencies "
    "— manifests and lockfiles (package.json, go.mod, pyproject.toml, "
    "requirements, Gemfile, etc.), infrastructure-as-code (Terraform, Helm, k8s, "
    "docker-compose), service config and env files, CI config, and any "
    "code/config that references other services or third-party APIs. The "
    "repository's root manifests (docker-compose, go.work, workspace files) "
    "often describe how components connect — read them too. Use your judgment "
    "about what's worth reading — you do NOT need to read everything; skip bulk "
    "application source. The graph shows COMPONENTS (deployable "
    "systems/services), not libraries. Classify what you find into one of:\n"
    "  • technologies — languages, frameworks, libraries, SDKs and tools the "
    "component USES (e.g. Next.js, React, FastAPI, Express, Terraform, the AWS "
    "SDK, zod, pydantic). These are NOT graph nodes — they become the "
    "component's tech labels. Put every imported package/framework/tool here.\n"
    "  • internal — a dependency on ANOTHER component in this workspace; only "
    "use the components listed in the roster, and return the component's "
    "exact ref as the target (a repository's full_path for its root component, "
    "full_path#path for a component inside a monorepo). Sibling components of "
    "this repository are in the roster too — a call to another service in the "
    "same repository IS an internal dependency.\n"
    "  • infrastructure — a datastore/queue/cache/object-store the component "
    "OWNS and operates as its own implementation detail (its Postgres/MySQL/"
    "Mongo database, Redis cache, Kafka/RabbitMQ/SQS queue, S3 bucket). These "
    "are stack-INTERNAL resources, not external services. Give each a `kind` of "
    "database, cache, queue, or storage.\n"
    "  • external_provider — a TRUE third-party SERVICE operated by another "
    "company that THIS component integrates with over the network: SaaS/APIs "
    "like Stripe, Auth0, SendGrid, Twilio, an external partner API. Do NOT put "
    "databases, caches, queues, object storage, or your own cloud infra here — "
    "those go in infrastructure. A client library/SDK is NOT a provider either — "
    "the SDK goes in technologies, the third-party service it calls goes here "
    "(e.g. 'Stripe SDK' is a technology, 'Stripe' is a provider). Do NOT list a "
    "bare cloud provider (AWS, GCP, Azure) — list the specific managed service "
    "as infrastructure instead.\n"
    "  • external_consumer — a system OUTSIDE the workspace that depends on THIS "
    "component (i.e. it exposes something the outside system consumes). NEVER "
    "list a roster component here — when a workspace component consumes this "
    "one, that's captured as the other component's internal dependency, not "
    "here. Infer external consumers only from real evidence: a public/published "
    "API or OpenAPI spec, a package published for outside use, inbound webhook "
    "endpoints (the external sender is the consumer), CORS allow-lists or "
    "registered external client IDs, or docs naming external clients. Be "
    "conservative — omit if there's no clear signal.\n"
    "Note a third party can be BOTH (e.g. you call Stripe's API = provider, and "
    "Stripe calls your webhook = consumer). Do not include this component "
    "itself, its repository, or other workspace components as external. When "
    "you have enough evidence, stop calling tools and return the structured "
    "result."
)


class _InternalDep(BaseModel):
    target: str = Field(description="ref of a roster component this component depends on")
    label: str = Field(default="", description="short edge caption, e.g. 'REST', 'events', 'OAuth'")


class _ExternalDep(BaseModel):
    name: str = Field(description="external system/service name, e.g. 'Stripe'")
    url: str = Field(default="", description="homepage/docs url if known")
    label: str = Field(default="", description="short caption, e.g. 'payments', 'webhooks'")


class _InfraDep(BaseModel):
    name: str = Field(description="datastore/queue/cache name, e.g. 'PostgreSQL'")
    kind: str = Field(default="other", description="database | cache | queue | storage")
    label: str = Field(default="", description="short caption, e.g. 'orders DB'")


class DependencyResult(BaseModel):
    technologies: list[str] = Field(
        default=[],
        description="languages/frameworks/libraries/tools used (tech labels, not nodes)",
    )
    internal: list[_InternalDep] = []
    infrastructure: list[_InfraDep] = Field(
        default=[], description="self-operated datastores/queues this component owns"
    )
    external_providers: list[_ExternalDep] = Field(
        default=[], description="true third-party services this component depends on"
    )
    external_consumers: list[_ExternalDep] = Field(
        default=[], description="external systems that depend on this component"
    )


def _roster_lines(roster: tuple[RosterEntry, ...]) -> list[str]:
    lines = []
    for e in roster:
        where = f"repo: {e.full_path}" if e.path else f"name: {e.name}"
        lines.append(f"  - ref: {e.ref}  ({where})")
    return lines


def _discovery_instructions(context: InferenceContext) -> str:
    return "\n".join(
        [
            f"Repository to analyze: {context.full_path}",
            "",
            "List the components this repository contains.",
        ]
    )


def _dependency_instructions(
    context: InferenceContext, component: ComponentDecl, roster: tuple[RosterEntry, ...]
) -> str:
    lines = [f"Repository: {context.full_path}"]
    if component.path:
        lines.append(
            f"Component to analyze: {component.name} at directory '{component.path}' "
            f"(one of several components in this repository)."
        )
    else:
        lines.append(f"Component to analyze: {component.name} (the whole repository).")
    lines += ["", "Workspace components (roster) you may reference as internal targets:"]
    lines += _roster_lines(roster) or ["  (none)"]
    lines += ["", "Inspect the component and return its internal and external dependencies."]
    return "\n".join(lines)


class LLMTopologyInference:
    """``TopologyInference`` over ``LLMAgent``. ``config`` is one resolved LLM
    role: ``{"model", "api_key", "base_url"}``."""

    def __init__(self, config: dict, *, agent_factory=None):
        self._config = config
        self._agent_factory = agent_factory or self._default_agent

    def _default_agent(self, log):
        return LLMAgent(
            model=self._config["model"],
            api_key=self._config.get("api_key"),
            base_url=self._config.get("base_url"),
            log=log,
        )

    def infer(self, snapshot: RepositorySnapshot, context: InferenceContext) -> RepositoryTopology:
        agent = self._agent_factory(context.log)
        toolbox = RepoToolbox(snapshot, context.full_path)

        discovery: ComponentDiscovery = agent.run(
            toolbox=toolbox,
            system_prompt=_DISCOVERY_PROMPT,
            instructions=_discovery_instructions(context),
            response_model=ComponentDiscovery,
        )
        components = normalise_components(
            (
                ComponentDecl(
                    path=c.path,
                    name=c.name,
                    kind=c.kind,
                    description=c.description,
                    technologies=tuple(c.technologies),
                )
                for c in discovery.components
            ),
            toolbox.load_tree(),
            context.project_name,
        )
        context.log(
            "discovery: " + (
                ", ".join(c.path or "<root>" for c in components)
            )
        )

        # Siblings join the roster so a component can depend on another one of
        # the same repository; they have no ids yet, the use case fills them.
        siblings = tuple(
            RosterEntry(full_path=context.full_path, path=c.path, name=c.name) for c in components
        )
        roster = context.roster + siblings

        final: list[ComponentDecl] = []
        internal: list[InternalDependency] = []
        externals: list[ExternalLink] = []
        infra: list[InfrastructureResource] = []
        for component in components:
            own = tuple(e for e in roster if not (e.full_path == context.full_path and e.path == component.path))
            result: DependencyResult = agent.run(
                toolbox=toolbox.scoped(component.path),
                system_prompt=_DEPENDENCY_PROMPT,
                instructions=_dependency_instructions(context, component, own),
                response_model=DependencyResult,
            )
            final.append(
                replace(
                    component,
                    technologies=clean_technologies(list(component.technologies) + list(result.technologies)),
                )
            )
            internal += [
                InternalDependency(component.path, d.target, d.label) for d in result.internal
            ]
            infra += [
                InfrastructureResource(component.path, d.name, d.kind, d.label)
                for d in result.infrastructure
            ]
            externals += [
                ExternalLink(component.path, d.name, OUTBOUND, d.url, d.label)
                for d in result.external_providers
            ]
            externals += [
                ExternalLink(component.path, d.name, INBOUND, d.url, d.label)
                for d in result.external_consumers
            ]

        context.log(
            f"{len(final)} components, {len(internal)} internal, {len(infra)} infra, "
            f"{len(externals)} external ({agent.usage['total_tokens']} tokens, "
            f"{agent.usage['calls']} calls, {len(toolbox.files_read)} files read)"
        )
        return RepositoryTopology(
            components=tuple(final),
            internal=tuple(internal),
            externals=tuple(externals),
            infrastructure=tuple(infra),
            evidence=Evidence(tree_size=toolbox.tree_size, files_read=tuple(toolbox.files_read)),
        )
