"""LLM dependency-inference use case.

Runs the in-process agent (``app.infrastructure.llm_agent``) against one
project's repository: the model lists/reads whatever config, IaC, manifest or
build files it judges relevant and returns the project's dependencies. We then
resolve those against the workspace's project roster — known projects become
``ProjectDependency`` edges, everything else becomes an ``ExternalDependency``
(third-party) — replacing the project's existing edges atomically.

Stack-to-stack edges are NOT written here; they're derived at read time
(see ``app.presentation.architecture``).
"""
from __future__ import annotations

import logging
from typing import Annotated

from django.db import transaction
from django.utils import timezone
from pydantic import BaseModel, Field

from app.application.naming import canonical_key
from app.application.policy_engine import resolve_llm_roles
from app.domain.models import (
    ExternalDependency,
    InfrastructureComponent,
    Project,
    ProjectDependency,
)
from app.infrastructure.llm_agent import LLMAgent, tool
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger(__name__)

ROLE = "reasoning"

# Backstop: common self-operated datastores/queues/storage. If the model files
# one of these as an external service, we reclassify it as infrastructure.
_INFRA_TERMS = {
    "postgres": "database", "postgresql": "database", "mysql": "database",
    "mariadb": "database", "sqlite": "database", "mongodb": "database",
    "mongo": "database", "dynamodb": "database", "cassandra": "database",
    "cockroach": "database", "rds": "database", "aurora": "database",
    "redis": "cache", "memcached": "cache",
    "kafka": "queue", "rabbitmq": "queue", "sqs": "queue", "sns": "queue",
    "kinesis": "queue", "pubsub": "queue", "nats": "queue",
    "s3": "storage", "gcs": "storage", "minio": "storage", "blob storage": "storage",
    "elasticsearch": "database", "opensearch": "database",
}


# Bare cloud providers aren't a specific external service — the concrete
# managed services (S3, SQS, RDS) are captured as infrastructure instead.
_GENERIC_CLOUD = {
    "aws", "amazon web services", "amazon", "gcp", "google cloud",
    "google cloud platform", "azure", "microsoft azure",
}


def _infra_kind(name: str) -> str | None:
    """Return an infrastructure kind if the name is a known datastore/queue, else None."""
    n = (name or "").lower()
    for term, kind in _INFRA_TERMS.items():
        if term in n:
            return kind
    return None



_SYSTEM_PROMPT = (
    "You are mapping the dependencies of one software repository for an "
    "architecture diagram. Use the tools to inspect the repo yourself: list "
    "files and read the ones that reveal dependencies — manifests and lockfiles "
    "(package.json, go.mod, pyproject.toml, requirements, Gemfile, etc.), "
    "infrastructure-as-code (Terraform, Helm, k8s, docker-compose), service "
    "config and env files, CI config, and any code/config that references other "
    "services or third-party APIs. Use your judgment about what's worth reading — "
    "you do NOT need to read everything; skip bulk application source. "
    "The graph shows COMPONENTS (deployable systems/services), not libraries. "
    "Classify what you find into one of:\n"
    "  • technologies — languages, frameworks, libraries, SDKs and tools the "
    "repo USES (e.g. Next.js, React, FastAPI, Express, Terraform, the AWS SDK, "
    "zod, pydantic). These are NOT graph nodes — they become the component's "
    "tech labels. Put every imported package/framework/tool here.\n"
    "  • internal — a dependency on ANOTHER repository in this workspace; only "
    "use the repositories listed in the roster, and return the repository's "
    "exact full_path as the target.\n"
    "  • infrastructure — a datastore/queue/cache/object-store the service OWNS "
    "and operates as its own implementation detail (its Postgres/MySQL/Mongo "
    "database, Redis cache, Kafka/RabbitMQ/SQS queue, S3 bucket). These are "
    "stack-INTERNAL components, not external services. Give each a `kind` of "
    "database, cache, queue, or storage.\n"
    "  • external_provider — a TRUE third-party SERVICE operated by another "
    "company that THIS repo integrates with over the network: SaaS/APIs like "
    "Stripe, Auth0, SendGrid, Twilio, an external partner API. Do NOT put "
    "databases, caches, queues, object storage, or your own cloud infra here — "
    "those go in infrastructure. A client library/SDK is NOT a provider either — "
    "the SDK goes in technologies, the third-party service it calls goes here "
    "(e.g. 'Stripe SDK' is a technology, 'Stripe' is a provider). Do NOT list a "
    "bare cloud provider (AWS, GCP, Azure) — list the specific managed service "
    "as infrastructure instead.\n"
    "  • external_consumer — a system OUTSIDE the workspace that depends on THIS "
    "repo (i.e. this repo exposes something it consumes). NEVER list a roster "
    "repository here — when a workspace repo consumes this one, that's captured "
    "as the other repo's internal dependency, not here. Infer external consumers "
    "only from real evidence in the repo: a public/published API or OpenAPI "
    "spec, a package published for outside use, inbound webhook endpoints the "
    "repo receives (the external sender is the consumer), CORS allow-lists or "
    "registered external client IDs, or docs naming external clients. Be "
    "conservative — omit if there's no clear signal.\n"
    "Note a third party can be BOTH (e.g. you call Stripe's API = provider, and "
    "Stripe calls your webhook = consumer). Do not include this repository "
    "itself or other workspace repos as external. When you have enough evidence, "
    "stop calling tools and return the structured result."
)


class _InternalDep(BaseModel):
    target: str = Field(description="full_path of a roster repository this repo depends on")
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
        default=[], description="self-operated datastores/queues this service owns"
    )
    external_providers: list[_ExternalDep] = Field(
        default=[], description="true third-party services this repo depends on"
    )
    external_consumers: list[_ExternalDep] = Field(
        default=[], description="external systems that depend on this repo"
    )


class _RepoToolbox:
    """Read-only repository tools handed to the model."""

    def __init__(self, client, full_path: str, ref: str):
        self._client = client
        self._full_path = full_path
        self._ref = ref
        self._tree: list[str] | None = None

    @tool
    def list_repo_files(
        self,
        path: Annotated[str, "Directory prefix to list; empty lists the whole repo"] = "",
    ) -> list:
        """List file paths in the repository (optionally under a directory)."""
        if self._tree is None:
            self._tree = self._client.get_tree(self._full_path, self._ref)
        if not path:
            return self._tree
        prefix = path.strip("/") + "/"
        return [p for p in self._tree if p.startswith(prefix)]

    @tool
    def read_file(
        self,
        path: Annotated[str, "File path relative to the repo root"],
    ) -> str:
        """Read a text file. Returns an empty string if missing or binary."""
        return self._client.get_file_content(self._full_path, path, self._ref) or ""


def _build_instructions(project: Project, roster: list[dict]) -> str:
    lines = [
        f"Repository to analyze: {project.full_path}",
        "",
        "Workspace repositories (roster) you may reference as internal targets:",
    ]
    for r in roster:
        lines.append(f"  - full_path: {r['full_path']}  (name: {r['name']})")
    lines += [
        "",
        "Inspect the repository and return its internal and external dependencies.",
    ]
    return "\n".join(lines)


def _resolve_internal_target(target: str, roster: list[dict]) -> str | None:
    """Map an LLM-returned target string to a roster project id (best effort)."""
    t = (target or "").strip().lower().rstrip("/")
    if not t:
        return None
    by_full_path = {r["full_path"].lower(): r["pk"] for r in roster}
    by_name = {r["name"].lower(): r["pk"] for r in roster}
    by_last = {r["full_path"].lower().rsplit("/", 1)[-1]: r["pk"] for r in roster}
    last = t.rsplit("/", 1)[-1]
    return by_full_path.get(t) or by_name.get(t) or by_name.get(last) or by_last.get(last)


def infer_and_store(project: Project) -> DependencyResult:
    """Analyze one project's repo and replace its dependency edges. Returns the
    raw model result. Sets the project's deps_status to OK on success; raises on
    failure (the caller/task records the failure)."""
    tenant = project.tenant
    roles = resolve_llm_roles(tenant)
    cfg = roles.get(ROLE)
    if not cfg:
        raise RuntimeError(
            f"No '{ROLE}' LLM role configured for this workspace — set it under "
            "Workspace Settings → LLM."
        )

    roster = list(
        Project.objects.filter(tenant=tenant)
        .exclude(pk=project.pk)
        .values("pk", "name", "full_path")
    )

    client = get_platform_client(project.platform_connection)
    toolbox = _RepoToolbox(client, project.full_path, project.default_branch)
    agent = LLMAgent(
        model=cfg["model"],
        api_key=cfg.get("api_key"),
        base_url=cfg.get("base_url"),
        log=lambda m: logger.info("deps[%s]: %s", project.name, m),
    )

    result: DependencyResult = agent.run(
        toolbox=toolbox,
        system_prompt=_SYSTEM_PROMPT,
        instructions=_build_instructions(project, roster),
        response_model=DependencyResult,
    )
    logger.info(
        "deps[%s]: %d internal, %d infra, %d providers, %d consumers (%d tokens, %d calls)",
        project.name,
        len(result.internal),
        len(result.infrastructure),
        len(result.external_providers),
        len(result.external_consumers),
        agent.usage["total_tokens"],
        agent.usage["calls"],
    )

    # Resolve + persist atomically (replace this project's outgoing edges).
    project_deps = []
    seen_targets = set()
    for dep in result.internal:
        target_pk = _resolve_internal_target(dep.target, roster)
        if not target_pk or target_pk == project.pk or target_pk in seen_targets:
            if not target_pk:
                logger.info("deps[%s]: unresolved internal target %r", project.name, dep.target)
            continue
        seen_targets.add(target_pk)
        project_deps.append(
            ProjectDependency(
                tenant=tenant, source=project, target_id=target_pk, label=dep.label[:255]
            )
        )

    # Infrastructure (internal datastores/queues this service owns).
    infra = {}
    _VALID_KINDS = {"database", "cache", "queue", "storage", "other"}

    def _add_infra(name, kind, label=""):
        name = (name or "").strip()
        key = name.lower()
        if not name or key in infra or _resolve_internal_target(name, roster):
            return
        if kind not in _VALID_KINDS:
            kind = _infra_kind(name) or "other"
        infra[key] = InfrastructureComponent(
            tenant=tenant, project=project, name=name[:255], kind=kind,
            description=(label or "")[:255],
        )

    for d in result.infrastructure:
        _add_infra(d.name, d.kind, d.label)

    external_deps = []

    def _collect(deps, direction):
        seen = set()
        for dep in deps:
            name = (dep.name or "").strip()
            if not name:
                continue
            # The LLM sometimes lists workspace repos as "external" — those
            # belong to internal ProjectDependency, captured elsewhere.
            if _resolve_internal_target(name, roster):
                logger.info("deps[%s]: dropping workspace repo %r from external", project.name, name)
                continue
            # Backstop: a datastore/queue is internal infrastructure, never an
            # external service (only applies to things we depend on).
            if direction == ExternalDependency.Direction.OUTBOUND:
                if name.lower() in _GENERIC_CLOUD:
                    continue  # bare cloud provider — its services are infra
                ik = _infra_kind(name)
                if ik:
                    _add_infra(name, ik, dep.label)
                    continue
            key = canonical_key(name)  # collapse "Stripe" / "Stripe API"
            if key in seen:
                continue
            seen.add(key)
            external_deps.append(
                ExternalDependency(
                    tenant=tenant,
                    project=project,
                    name=name[:255],
                    direction=direction,
                    url=(dep.url or "")[:2048],
                    description=dep.label[:255],
                )
            )

    _collect(result.external_providers, ExternalDependency.Direction.OUTBOUND)
    _collect(result.external_consumers, ExternalDependency.Direction.INBOUND)
    infra_components = list(infra.values())

    # Inferred tech labels (deduped, capped); merged with GitHub languages at
    # render time.
    technologies = []
    seen_tech = set()
    for t in result.technologies:
        t = (t or "").strip()
        key = t.lower()
        if t and key not in seen_tech:
            seen_tech.add(key)
            technologies.append(t[:60])

    with transaction.atomic():
        ProjectDependency.objects.filter(tenant=tenant, source=project).delete()
        ExternalDependency.objects.filter(tenant=tenant, project=project).delete()
        InfrastructureComponent.objects.filter(tenant=tenant, project=project).delete()
        ProjectDependency.objects.bulk_create(project_deps, ignore_conflicts=True)
        ExternalDependency.objects.bulk_create(external_deps, ignore_conflicts=True)
        InfrastructureComponent.objects.bulk_create(infra_components, ignore_conflicts=True)
        project.inferred_technologies = technologies[:20]
        project.deps_status = Project.DepsStatus.OK
        project.deps_analyzed_at = timezone.now()
        project.deps_error = ""
        project.save(
            update_fields=[
                "inferred_technologies",
                "deps_status",
                "deps_analyzed_at",
                "deps_error",
            ]
        )

    return result
