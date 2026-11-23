"""LLM-backed ``TopologyInference``: runs of the in-process agent.

**Discovery (whole-repository projects only).** The model lists the
repository and names the independently deployable/publishable units it
contains — a monorepo's apps, services and libraries. They become *suggested
projects*: offered on the project page, each to be added as a project of its
own. A plain single-application repository yields none.

**Dependencies.** The model gets a toolbox whose default listing is scoped to
the project's directory, minus the directories other projects on the
repository own (``read_file`` stays repository-wide so root manifests remain
readable), and returns the project's internal, infrastructure and external
dependencies plus its tech labels.

Two runs rather than one nested answer because ``LLMAgent.run`` caps each run
at ``MAX_ITERATIONS`` / ``MAX_TOOL_CALLS``: discovery and dependency mapping
each need their own budget of reads.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.application.architecture.ports import InferenceContext, RepositorySnapshot
from app.domain.architecture.resolve import RosterEntry
from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    Evidence,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    ProjectTopology,
    clean_technologies,
)
from app.domain.projects import SuggestedProject
from app.infrastructure.llm_agent import LLMAgent
from app.infrastructure.topology.toolbox import RepoToolbox

ROLE = "reasoning"


# --- Discovery: the units inside a repository ------------------------------------

_DISCOVERY_PROMPT = (
    "You are identifying the UNITS of one software repository for an "
    "architecture diagram: the independently deployable or publishable parts "
    "it contains — services/APIs, frontends/apps, shared libraries, jobs and "
    "pipelines, infrastructure-as-code roots. Use the tools to look at the "
    "repository yourself.\n"
    "Evidence that a repository holds SEVERAL units: workspace manifests "
    "(package.json `workspaces`, pnpm-workspace.yaml, turbo.json, nx.json, "
    "lerna.json, `[tool.uv.workspace]` / Poetry workspaces in pyproject.toml, "
    "go.work, a Cargo workspace), docker-compose `build:` contexts pointing at "
    "sub-directories, per-directory Dockerfiles or manifests, CODEOWNERS, a "
    "README that lists the parts, conventional folders such as apps/, "
    "services/, packages/, libs/, infra/.\n"
    "A repository with ONE manifest at its root and no such evidence is ONE "
    "unit at path '' (the repository root) — this is the common case; do "
    "not invent units for ordinary folders like src/, tests/, docs/.\n"
    "Do not list every folder: list units that are built, deployed or "
    "published on their own. Give each a repository-relative directory path, "
    "a short name (usually the directory name or the manifest's package name), "
    "a kind (service | frontend | library | job | infra | other), a one-line "
    "description, and the languages/frameworks you can see in its manifest. "
    "Return at most 25 units. When you have enough evidence, stop calling "
    "tools and return the structured result."
)


class _Unit(BaseModel):
    path: str = Field(description="repository-relative directory, '' for the repository root")
    name: str = Field(default="", description="short name")
    kind: str = Field(default="other", description="service | frontend | library | job | infra | other")
    description: str = Field(default="", description="one line: what this unit is")
    technologies: list[str] = Field(default=[], description="languages/frameworks seen in its manifest")


class UnitDiscovery(BaseModel):
    units: list[_Unit] = []


# --- Dependencies of one project ----------------------------------------------------

_DEPENDENCY_PROMPT = (
    "You are mapping the dependencies of one software PROJECT (a deployable "
    "unit: a whole repository, or one directory of a monorepo) for an "
    "architecture diagram. Use the tools to "
    "inspect it yourself: list files and read the ones that reveal dependencies "
    "— manifests and lockfiles (package.json, go.mod, pyproject.toml, "
    "requirements, Gemfile, etc.), infrastructure-as-code (Terraform, Helm, k8s, "
    "docker-compose), service config and env files, CI config, and any "
    "code/config that references other services or third-party APIs. The "
    "repository's root manifests (docker-compose, go.work, workspace files) "
    "often describe how projects connect — read them too. Use your judgment "
    "about what's worth reading — you do NOT need to read everything; skip bulk "
    "application source. The graph shows PROJECTS (deployable "
    "systems/services), not libraries. Classify what you find into one of:\n"
    "  • technologies — languages, frameworks, libraries, SDKs and tools the "
    "project USES (e.g. Next.js, React, FastAPI, Express, Terraform, the AWS "
    "SDK, zod, pydantic). These are NOT graph nodes — they become the "
    "project's tech labels. Put every imported package/framework/tool here.\n"
    "  • internal — a dependency on ANOTHER project in this workspace; only "
    "use the projects listed in the roster, and return the project's "
    "exact ref as the target (a repository's full_path for a whole-repository "
    "project, full_path#path for a project inside a monorepo). Other projects "
    "of this repository are in the roster too — a call to another service in the "
    "same repository IS an internal dependency.\n"
    "  • infrastructure — a datastore/queue/cache/object-store the project "
    "OWNS and operates as its own implementation detail (its Postgres/MySQL/"
    "Mongo database, Redis cache, Kafka/RabbitMQ/SQS queue, S3 bucket). These "
    "are stack-INTERNAL resources, not external services. Give each a `kind` of "
    "database, cache, queue, or storage.\n"
    "  • external_provider — a TRUE third-party SERVICE operated by another "
    "company that THIS project integrates with over the network: SaaS/APIs "
    "like Stripe, Auth0, SendGrid, Twilio, an external partner API. Do NOT put "
    "databases, caches, queues, object storage, or your own cloud infra here — "
    "those go in infrastructure. A client library/SDK is NOT a provider either — "
    "the SDK goes in technologies, the third-party service it calls goes here "
    "(e.g. 'Stripe SDK' is a technology, 'Stripe' is a provider). Do NOT list a "
    "bare cloud provider (AWS, GCP, Azure) — list the specific managed service "
    "as infrastructure instead.\n"
    "  • external_consumer — a system OUTSIDE the workspace that depends on THIS "
    "project (i.e. it exposes something the outside system consumes). NEVER "
    "list a roster project here — when a workspace project consumes this "
    "one, that's captured as the other project's internal dependency, not "
    "here. Infer external consumers only from real evidence: a public/published "
    "API or OpenAPI spec, a package published for outside use, inbound webhook "
    "endpoints (the external sender is the consumer), CORS allow-lists or "
    "registered external client IDs, or docs naming external clients. Be "
    "conservative — omit if there's no clear signal.\n"
    "Note a third party can be BOTH (e.g. you call Stripe's API = provider, and "
    "Stripe calls your webhook = consumer). Do not include this project "
    "itself, its repository, or other workspace projects as external. When "
    "you have enough evidence, stop calling tools and return the structured "
    "result."
)


class _InternalDep(BaseModel):
    target: str = Field(description="ref of a roster project this project depends on")
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
        default=[], description="self-operated datastores/queues this project owns"
    )
    external_providers: list[_ExternalDep] = Field(
        default=[], description="true third-party services this project depends on"
    )
    external_consumers: list[_ExternalDep] = Field(
        default=[], description="external systems that depend on this project"
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
            "List the independently built or deployed units this repository contains.",
        ]
    )


def _dependency_instructions(context: InferenceContext) -> str:
    lines = [f"Repository: {context.full_path}"]
    if context.root_path:
        lines.append(
            f"Project to analyze: {context.project_name} at directory '{context.root_path}' "
            f"(one of several projects in this repository)."
        )
    else:
        lines.append(f"Project to analyze: {context.project_name} (the whole repository).")
    if context.excluded_paths:
        lines.append(
            "These directories are other projects of their own; leave them out: "
            + ", ".join(context.excluded_paths)
        )
    lines += ["", "Workspace projects (roster) you may reference as internal targets:"]
    lines += _roster_lines(context.roster) or ["  (none)"]
    lines += ["", "Inspect the project and return its internal and external dependencies."]
    return "\n".join(lines)


class LLMTopologyInference:
    """``TopologyInference`` over ``LLMAgent``. ``config`` is one resolved LLM
    role: ``{"model", "api_key", "base_url"}``."""

    def __init__(self, config: dict, *, agent_factory=None):
        self._config = config
        self._agent_factory = agent_factory or self._default_agent
        # The last ``infer``'s token usage (input/output/calls), kept even
        # when it failed part-way: those tokens were spent all the same.
        self.usage: dict = {}

    @property
    def provider_id(self):
        return self._config.get("provider_id")

    @property
    def model_name(self) -> str:
        return self._config.get("model_name") or self._config.get("model", "")

    def _default_agent(self, log):
        return LLMAgent(
            model=self._config["model"],
            api_key=self._config.get("api_key"),
            base_url=self._config.get("base_url"),
            log=log,
        )

    def infer(self, snapshot: RepositorySnapshot, context: InferenceContext) -> ProjectTopology:
        agent = self._agent_factory(context.log)
        self.usage = agent.usage  # the same dict: it fills in as the agent runs
        toolbox = RepoToolbox(snapshot, context.full_path)

        suggestions: tuple[SuggestedProject, ...] = ()
        if context.discover:
            discovery: UnitDiscovery = agent.run(
                toolbox=toolbox,
                system_prompt=_DISCOVERY_PROMPT,
                instructions=_discovery_instructions(context),
                response_model=UnitDiscovery,
            )
            suggestions = SuggestedProject.from_discovery(
                (
                    SuggestedProject(
                        path=u.path,
                        name=u.name,
                        kind=u.kind,
                        description=u.description,
                        technologies=tuple(u.technologies),
                    )
                    for u in discovery.units
                ),
                toolbox.load_tree(),
            )
            context.log("discovery: " + (", ".join(s.path for s in suggestions) or "a single unit"))

        result: DependencyResult = agent.run(
            toolbox=toolbox.scoped(context.root_path, exclude=context.excluded_paths),
            system_prompt=_DEPENDENCY_PROMPT,
            instructions=_dependency_instructions(context),
            response_model=DependencyResult,
        )
        internal = tuple(InternalDependency(d.target, d.label) for d in result.internal)
        infra = tuple(InfrastructureResource(d.name, d.kind, d.label) for d in result.infrastructure)
        externals = tuple(
            [ExternalLink(d.name, OUTBOUND, d.url, d.label) for d in result.external_providers]
            + [ExternalLink(d.name, INBOUND, d.url, d.label) for d in result.external_consumers]
        )

        context.log(
            f"{len(suggestions)} suggested, {len(internal)} internal, {len(infra)} infra, "
            f"{len(externals)} external ({agent.usage['total_tokens']} tokens, "
            f"{agent.usage['calls']} calls, {len(toolbox.files_read)} files read)"
        )
        return ProjectTopology(
            technologies=clean_technologies(result.technologies),
            internal=internal,
            externals=externals,
            infrastructure=infra,
            suggestions=suggestions,
            evidence=Evidence(tree_size=toolbox.tree_size, files_read=tuple(toolbox.files_read)),
        )
