import secrets
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse

from app.domain.notifications import Kind, Severity, first_line
from app.infrastructure.model_fields import EncryptedCharField


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    avatar_url = models.URLField(max_length=2048, blank=True, default="")

    class Meta:
        db_table = "users"


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants"
        ordering = ["created_at"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tenant"], name="unique_user_tenant"
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.tenant} ({self.role})"


class Platform(models.TextChoices):
    GITHUB = "github", "GitHub"
    GITLAB = "gitlab", "GitLab"


class AuthMethod(models.TextChoices):
    PAT = "pat", "Personal Access Token"
    GITHUB_APP = "github_app", "GitHub App"


class PlatformConnection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="platform_connections",
    )
    platform = models.CharField(max_length=10, choices=Platform.choices)
    display_name = models.CharField(max_length=255)
    base_url = models.URLField(max_length=2048)
    # PAT connections store the encrypted token here; GitHub App connections
    # mint short-lived installation tokens on demand instead, so this is
    # nullable/blank for them.
    access_token = EncryptedCharField(max_length=1024, null=True, blank=True)
    # How this connection authenticates. Defaults to "pat" so existing rows
    # and PAT behavior are unchanged.
    auth_method = models.CharField(
        max_length=20,
        choices=AuthMethod.choices,
        default=AuthMethod.PAT,
    )
    # GitHub App installation details (populated only for github_app connections).
    installation_id = models.BigIntegerField(null=True, blank=True)
    account_login = models.CharField(max_length=255, null=True, blank=True)
    account_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_connections"

    def __str__(self):
        return f"{self.display_name} ({self.platform})"

    @property
    def github_app_manage_url(self):
        """Deep-link to GitHub's installation settings for App connections.

        Returns the org-scoped settings URL for Organization installations and
        the personal settings URL otherwise. Falsy (``None``) for PAT
        connections or App connections missing an ``installation_id``.
        """
        if self.auth_method != AuthMethod.GITHUB_APP or not self.installation_id:
            return None
        if self.account_type == "Organization" and self.account_login:
            return (
                f"https://github.com/organizations/{self.account_login}"
                f"/settings/installations/{self.installation_id}"
            )
        return f"https://github.com/settings/installations/{self.installation_id}"

    def get_access_token(self, repositories=None):
        """Return an access token usable for platform API calls.

        PAT connections return the stored (decrypted) token. GitHub App
        connections mint a short-lived installation token on demand, optionally
        scoped to ``repositories``.
        """
        if self.auth_method == AuthMethod.GITHUB_APP:
            # Local import avoids a module-load cycle (domain ← infrastructure).
            from app.infrastructure import github_app

            return github_app.get_installation_token(
                self.installation_id, repositories
            )
        return self.access_token

    def save(self, *args, **kwargs):
        if not self.base_url:
            self.base_url = (
                "https://api.github.com"
                if self.platform == Platform.GITHUB
                else "https://gitlab.com"
            )
        super().save(*args, **kwargs)


class LLMProviderType(models.TextChoices):
    """Provider identifiers that map directly to LiteLLM's provider prefixes.

    A configured model is handed to LiteLLM as ``f"{provider_type}/{model}"``
    (e.g. ``anthropic/claude-opus-4``, ``litellm_proxy/qwen-coder``), so these
    values intentionally mirror LiteLLM's provider IDs — no translation layer.
    """

    ANTHROPIC = "anthropic", "Anthropic"
    OPENAI = "openai", "OpenAI"
    AZURE = "azure", "Azure OpenAI"
    BEDROCK = "bedrock", "AWS Bedrock"
    VERTEX_AI = "vertex_ai", "Google Vertex AI"
    GEMINI = "gemini", "Google Gemini"
    MISTRAL = "mistral", "Mistral"
    OLLAMA = "ollama", "Ollama"
    LITELLM_PROXY = "litellm_proxy", "LiteLLM Proxy"


class LLMProvider(models.Model):
    """A workspace's LLM credential + endpoint. Mirrors PlatformConnection:
    a tenant can have many, including several of the same type with different
    keys. ``available_models`` is populated by discovery or manual entry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="llm_providers",
    )
    provider_type = models.CharField(
        max_length=20, choices=LLMProviderType.choices
    )
    display_name = models.CharField(max_length=255)
    base_url = models.URLField(max_length=2048, blank=True, default="")
    api_key = EncryptedCharField(max_length=1024)
    available_models = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "llm_providers"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.display_name} ({self.provider_type})"


class LLMRole(models.Model):
    """Maps a fixed, code-defined role to a (provider, model) pair.

    The role set is static because the sandbox ``llm`` object exposes these
    roles as attributes in code (``llm.reasoning``, ``llm.code``). Users assign
    a provider + model to each role; they cannot invent new roles. Adding a
    role is a deliberate code change on both the app and sandbox sides.
    """

    class Name(models.TextChoices):
        REASONING = "reasoning", "Reasoning"
        CODE = "code", "Code"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="llm_roles",
    )
    name = models.CharField(max_length=20, choices=Name.choices)
    provider = models.ForeignKey(
        LLMProvider,
        on_delete=models.CASCADE,
        related_name="roles",
    )
    model = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "llm_roles"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"], name="unique_tenant_role"
            ),
        ]

    def __str__(self):
        return f"{self.name} → {self.provider.display_name}/{self.model}"


class Project(models.Model):
    class Lifecycle(models.TextChoices):
        DEVELOPMENT = "development", "Development"
        STAGING = "staging", "Staging"
        PRODUCTION = "production", "Production"
        MAINTENANCE = "maintenance", "Maintenance"
        DEPRECATED = "deprecated", "Deprecated"
        ARCHIVED = "archived", "Archived"

    class DepsStatus(models.TextChoices):
        """State of the LLM dependency-inference run for this project."""

        NONE = "none", "Not analyzed"
        PENDING = "pending", "Queued"
        RUNNING = "running", "Analyzing"
        OK = "ok", "Analyzed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    platform_connection = models.ForeignKey(
        PlatformConnection,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    platform = models.CharField(max_length=10, choices=Platform.choices)
    external_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    full_path = models.CharField(max_length=2048)
    web_url = models.URLField(max_length=2048)
    default_branch = models.CharField(max_length=255, default="main")
    webhook_id = models.CharField(max_length=255, blank=True, default="")
    webhook_secret = models.CharField(max_length=255, blank=True, default="")
    lifecycle = models.CharField(
        max_length=20,
        choices=Lifecycle.choices,
        default=Lifecycle.DEVELOPMENT,
    )
    owner = models.CharField(max_length=255, blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    languages = models.JSONField(default=list, blank=True)
    # LLM dependency-inference status (drives the dashboard "regenerating…" hint).
    deps_status = models.CharField(
        max_length=10,
        choices=DepsStatus.choices,
        default=DepsStatus.NONE,
    )
    deps_analyzed_at = models.DateTimeField(null=True, blank=True)
    deps_error = models.TextField(blank=True, default="")
    # Repository files the model actually read to build this map (capped at
    # 50). Empty until an analysis completes; lets anyone see what a map is
    # grounded in.
    deps_evidence = models.JSONField(default=list, blank=True)
    standards = models.ManyToManyField(
        "Standard",
        through="ProjectStandard",
        blank=True,
        related_name="projects",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform_connection", "external_id"],
                name="unique_tenant_connection_project",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

    # --- Components -----------------------------------------------------------
    # A project is one git repository. Its *components* are the deployable
    # units inside it (see ``Component``); a plain single-application repo has
    # exactly one, the root component. Stack membership, dependencies and
    # infrastructure hang off components, so these helpers give the
    # repo-level view the rest of the app still mostly wants.

    @property
    def root_component(self):
        """The component at the repository root (``path == ""``)."""
        return self.components.filter(path="").first()

    @property
    def is_monorepo(self) -> bool:
        """True when the repository holds more than one component."""
        return self.components.count() > 1

    @property
    def stacks(self):
        """Stacks any of this project's components belong to (read-only)."""
        return Stack.objects.filter(components__project=self).distinct()


class Stack(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="stacks",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stacks"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def projects(self):
        """Distinct projects with at least one component in this stack (read-only)."""
        return Project.objects.filter(components__stacks=self).distinct()


class Component(models.Model):
    """A buildable/deployable unit inside a project's repository.

    A *project* is one git repository; a *component* is what actually gets
    built or deployed from it: a service, a frontend, a shared library, a
    job, an infrastructure-as-code root. Every project has at least one
    component. A plain single-application repository has exactly one, the
    *root component* (``path == ""``); a monorepo has several, each rooted at
    a sub-directory. Stack membership, dependency edges and owned
    infrastructure attach to components, never to projects, so the
    architecture diagram has one node type regardless of repository shape.

    Components are discovered by the dependency-inference agent and
    reconciled by ``path`` on every run, so an unchanged component keeps its
    id (and therefore its stack memberships) across re-analysis.
    """

    class Kind(models.TextChoices):
        SERVICE = "service", "Service / API"
        FRONTEND = "frontend", "Frontend / app"
        LIBRARY = "library", "Shared library"
        JOB = "job", "Job / pipeline"
        INFRA = "infra", "Infrastructure as code"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="components",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="components",
    )
    # Repository-relative directory, normalised: no leading/trailing slash,
    # "" for the repository root.
    path = models.CharField(max_length=1024, blank=True, default="")
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OTHER)
    description = models.TextField(blank=True, default="")
    # Frameworks/libraries/tools inferred by the LLM (e.g. Next.js, FastAPI,
    # Terraform). Merged + deduped with the project's `languages` to form the
    # node's tech labels, so libraries show as labels, not as graph nodes.
    technologies = models.JSONField(default=list, blank=True)
    stacks = models.ManyToManyField(
        Stack,
        through="ComponentStack",
        blank=True,
        related_name="components",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "components"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "path"], name="unique_component_path"
            ),
        ]
        ordering = ["project__name", "path"]

    def __str__(self):
        return self.name if self.is_root else f"{self.project} / {self.path}"

    @property
    def is_root(self) -> bool:
        return self.path == ""

    @property
    def ref(self) -> str:
        """How the roster names this component to the model and to users:
        the repository's ``full_path`` for a root component,
        ``<full_path>#<path>`` for a component inside a monorepo."""
        return self.project.full_path if self.is_root else f"{self.project.full_path}#{self.path}"


class ComponentStack(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    component = models.ForeignKey(
        Component,
        on_delete=models.CASCADE,
        related_name="component_stacks",
    )
    stack = models.ForeignKey(
        Stack,
        on_delete=models.CASCADE,
        related_name="component_stacks",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "component_stacks"
        constraints = [
            models.UniqueConstraint(
                fields=["component", "stack"], name="unique_component_stack"
            ),
        ]

    def __str__(self):
        return f"{self.component} — {self.stack}"


class ProjectStandard(models.Model):
    """Attachment of a workspace standard to a project.

    Only attached standards are candidates to run on a project; criteria
    (events, ref regex, languages) still filter within the attached set.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="project_standards",
    )
    standard = models.ForeignKey(
        "Standard",
        on_delete=models.CASCADE,
        related_name="project_standards",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "project_standards"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "standard"], name="unique_project_standard"
            ),
        ]

    def __str__(self):
        return f"{self.project} — {self.standard}"


class StackDependency(models.Model):
    """A directed dependency between two stacks in a workspace.

    Renders as an edge in the dashboard architecture diagram (source depends
    on target). These are populated/maintained by an LLM as stacks and
    projects change; the optional ``label`` is the edge caption (e.g.
    "REST", "events", "shared DB").
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="stack_dependencies",
    )
    source = models.ForeignKey(
        Stack,
        on_delete=models.CASCADE,
        related_name="dependencies_out",
    )
    target = models.ForeignKey(
        Stack,
        on_delete=models.CASCADE,
        related_name="dependencies_in",
    )
    label = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stack_dependencies"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target"], name="unique_stack_dependency"
            ),
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")),
                name="stack_dependency_no_self_loop",
            ),
        ]

    def __str__(self):
        return f"{self.source} → {self.target}"


class ComponentDependency(models.Model):
    """A directed dependency between two components in a workspace.

    Renders as an edge in the per-stack architecture diagram (source depends
    on target). When the two components live in different stacks the edge
    crosses a stack boundary — that's how the stack view surfaces which of a
    stack's components are public-facing (consumed from outside) and which
    reach out to components in other stacks. Two components of the same
    monorepo may depend on each other. Maintained by an LLM as repositories
    change; ``label`` is the optional edge caption.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="component_dependencies",
    )
    source = models.ForeignKey(
        Component,
        on_delete=models.CASCADE,
        related_name="dependencies_out",
    )
    target = models.ForeignKey(
        Component,
        on_delete=models.CASCADE,
        related_name="dependencies_in",
    )
    label = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "component_dependencies"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target"], name="unique_component_dependency"
            ),
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")),
                name="component_dependency_no_self_loop",
            ),
        ]

    def __str__(self):
        return f"{self.source} → {self.target}"


class ExternalDependency(models.Model):
    """A relationship between a workspace component and a system outside the
    workspace.

    Direction distinguishes the two roles (both inferred by inspecting the
    component's repository):
      * ``OUTBOUND`` — the component depends on an external service/provider
        (e.g. Stripe, Auth0). Rendered at the bottom of the stack diagram.
      * ``INBOUND`` — an external consumer depends on the component (e.g. a
        public API client, a partner system, external webhook senders).
        Rendered at the top (we must preserve its API).

    Unlike ComponentDependency (which links two workspace components), the
    other end here is outside the workspace. Maintained by an LLM.
    """

    class Direction(models.TextChoices):
        OUTBOUND = "outbound", "We depend on it (provider)"
        INBOUND = "inbound", "It depends on us (consumer)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="external_dependencies",
    )
    component = models.ForeignKey(
        Component,
        on_delete=models.CASCADE,
        related_name="external_dependencies",
    )
    name = models.CharField(max_length=255)
    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        default=Direction.OUTBOUND,
    )
    url = models.URLField(max_length=2048, blank=True, default="")
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "external_dependencies"
        constraints = [
            models.UniqueConstraint(
                fields=["component", "name", "direction"],
                name="unique_external_dependency",
            ),
        ]

    def __str__(self):
        arrow = "←" if self.direction == self.Direction.INBOUND else "→"
        return f"{self.component} {arrow} {self.name}"


class InfrastructureComponent(models.Model):
    """A self-operated datastore/queue/cache/storage a component owns.

    These are stack-INTERNAL resources (a service abstracts its own
    databases), not external services — rendered as internal nodes inside the
    stack diagram, not on the workspace graph. Per-component: two services
    with their own Postgres are two separate nodes. Maintained by an LLM.
    """

    class Kind(models.TextChoices):
        DATABASE = "database", "Database"
        CACHE = "cache", "Cache"
        QUEUE = "queue", "Queue / Stream"
        STORAGE = "storage", "Object storage"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="infrastructure_components",
    )
    component = models.ForeignKey(
        Component,
        on_delete=models.CASCADE,
        related_name="infrastructure_components",
    )
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OTHER)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "infrastructure_components"
        constraints = [
            models.UniqueConstraint(
                fields=["component", "name"], name="unique_infrastructure_component"
            ),
        ]

    def __str__(self):
        return f"{self.component} ⟐ {self.name}"


class APIToken(models.Model):
    class ClientKind(models.TextChoices):
        CLAUDE = "claude", "Claude Code / Desktop"
        GENERIC = "generic", "Generic MCP client"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    name = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(max_length=16)
    client_kind = models.CharField(
        max_length=10,
        choices=ClientKind.choices,
        default=ClientKind.CLAUDE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "api_tokens"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.prefix}... ({self.tenant})"

    @classmethod
    def generate(cls, client_kind: str = ClientKind.CLAUDE) -> tuple["APIToken", str]:
        """Return an unsaved APIToken instance and the raw token string."""
        import hashlib
        raw = "grit_" + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        prefix = raw[:12]
        instance = cls(token_hash=token_hash, prefix=prefix, client_kind=client_kind)
        return instance, raw


class StandardLabel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="standard_labels",
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "standard_labels"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="unique_label_per_tenant",
            ),
        ]

    def __str__(self):
        return self.name


class Standard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="standards",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    code = models.TextField(
        default='def evaluate(project):\n    return {"passed": True, "score": 100, "message": "OK", "details": {}}\n'
    )
    criteria = models.JSONField(default=dict, blank=True)
    test_cases = models.JSONField(default=list, blank=True)
    labels = models.ManyToManyField(StandardLabel, related_name="standards", blank=True)
    source_marketplace_standard = models.ForeignKey(
        "MarketplaceStandard",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="installed_standards",
    )
    source_version = models.IntegerField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    draft = models.BooleanField(default=False)
    ordinal = models.IntegerField(default=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "standards"
        ordering = ["ordinal", "name"]

    def __str__(self):
        return self.name


class StandardVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    standard = models.ForeignKey(
        Standard,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.IntegerField()
    code = models.TextField()
    description = models.TextField(blank=True, default="")
    criteria = models.JSONField(default=dict, blank=True)
    test_cases = models.JSONField(default=list, blank=True)
    labels_snapshot = models.JSONField(default=list, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    change_summary = models.CharField(max_length=255, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "standard_versions"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["standard", "version"],
                name="unique_standard_version",
            ),
        ]

    def __str__(self):
        return f"{self.standard.name} v{self.version}"


class MarketplaceStandard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    code = models.TextField()
    test_cases = models.JSONField(default=list, blank=True)
    criteria = models.JSONField(default=dict, blank=True)
    suggested_labels = models.JSONField(default=list, blank=True)
    version = models.IntegerField(default=1)
    author = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "marketplace_standards"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} v{self.version}"


class MarketplacePack(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=10, blank=True, default="")
    standards = models.ManyToManyField(
        MarketplaceStandard, related_name="packs", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "marketplace_packs"
        ordering = ["name"]

    def __str__(self):
        return self.name


class StandardExecution(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        ERROR = "error", "Error"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="standard_executions",
    )
    standard = models.ForeignKey(
        Standard,
        on_delete=models.SET_NULL,
        null=True,
        related_name="executions",
    )
    standard_name = models.CharField(max_length=255)
    event_type = models.CharField(max_length=50)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    score = models.IntegerField(default=0)
    message = models.TextField(blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    # Chronological execution log (level/message/t_ms entries) captured from the
    # sandbox — author log() calls plus the LLM agentic trace. Shown on the
    # execution detail page to help debug why a standard failed.
    logs = models.JSONField(default=list, blank=True)
    triggered_by = models.CharField(max_length=255, blank=True, default="")
    triggered_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="standard_executions",
    )
    ref = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "standard_executions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["project", "-created_at"],
                name="idx_standardexec_project_date",
            ),
            models.Index(
                fields=["standard", "-created_at"],
                name="idx_standardexec_standard_date",
            ),
        ]

    def __str__(self):
        return f"{self.standard_name} — {self.status} ({self.project})"


class FeedbackReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_reports",
    )
    user_email = models.CharField(max_length=320, blank=True, default="")
    tenant_slug = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField()
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedback_reports"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Feedback from {self.user_email or self.user_id or 'anonymous'} @ {self.created_at:%Y-%m-%d}"


class Notification(models.Model):
    """Aggregate root: one thing that happened in a workspace that people should
    hear about. It is a fact, not a message to anyone: who hears it is decided
    by notification routing
    (``app.domain.notifications.notification_routing``).

    Immutable once raised. Created only through the named constructors below
    (``could_not_evaluate``, ``standards_failing``, ``graph_failed``), which
    hold each kind's wording, severity and link.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=100)
    severity = models.CharField(
        max_length=10,
        choices=[(s.value, s.value.title()) for s in Severity],
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=500, blank=True)
    # Facts the screens and notification routing read: project id and name,
    # execution ids, trigger, score, and who triggered the run. Ids and short
    # values only; anything bigger is loaded from its own table.
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["tenant", "created_at"],
                name="idx_notification_tenant_date",
            ),
        ]

    def __str__(self):
        return f"{self.kind} — {self.title}"

    @property
    def triggered_by_user_ids(self) -> list[str]:
        """Users who started the run behind this notification, if any."""
        return list(self.context.get("triggered_by_user_ids", []))

    @property
    def subject(self) -> str:
        """What the notification is about, for its row: a project, a
        connection, a standard, a person. Older rows only named a project."""
        return self.context.get("subject") or self.context.get("project_name", "")

    @property
    def member_user_id(self) -> str | None:
        """The workspace member a membership notification is about."""
        return self.context.get("member_user_id")

    @property
    def actor_user_id(self) -> str | None:
        """Who made the change behind this notification, if a person did."""
        return self.context.get("actor_user_id")

    # --- Named constructors: one per kind ------------------------------------
    # Runs

    @classmethod
    def could_not_evaluate(
        cls, *, project, error, execution_id=None, execution_ids=(), trigger=None,
        triggered_by_user_ids=(),
    ):
        """A run could not complete at all. Critical: the project keeps
        showing its old score, so the workspace looks healthy when it is not.
        Links to the failed run's details, or the project when there is none."""
        url = (
            reverse("standard_execution_detail", args=[execution_id])
            if execution_id
            else reverse("project_detail", args=[project.pk])
        )
        return cls._new(
            project=project,
            kind=Kind.RUN_FAILED,
            severity=Severity.CRITICAL,
            title="GitGrit could not evaluate",
            body=first_line(error),
            url=url,
            context=_run_context(execution_ids, trigger, triggered_by_user_ids),
        )

    @classmethod
    def standards_failing(
        cls, *, project, failed_names, failed_standard_ids, execution_ids=(), score=None,
        trigger=None, triggered_by_user_ids=(),
    ):
        """A run finished with failed standards: one notification per run,
        naming up to three. ``score`` is the project's overall score."""
        n = len(failed_names)
        listing = ", ".join(failed_names[:3])
        if n > 3:
            listing += f" and {n - 3} more"
        context = _run_context(execution_ids, trigger, triggered_by_user_ids)
        context["failed_standard_ids"] = [str(i) for i in failed_standard_ids]
        if score is not None:
            context["score"] = round(score)
        return cls._new(
            project=project,
            kind=Kind.STANDARDS_FAILING,
            severity=Severity.WARNING,
            title=f"{n} standard{'s' if n != 1 else ''} failed",
            body=first_line(listing),
            url=reverse("project_detail", args=[project.pk]) + "#compliance",
            context=context,
        )

    @classmethod
    def project_turned_critical(
        cls, *, project, score_before, score_after, execution_ids=(), trigger=None,
        triggered_by_user_ids=(),
    ):
        """A run dropped the project's overall score into critical."""
        context = _run_context(execution_ids, trigger, triggered_by_user_ids)
        context["score"] = round(score_after)
        return cls._new(
            project=project,
            kind=Kind.PROJECT_CRITICAL,
            severity=Severity.CRITICAL,
            title="Score dropped to critical",
            body=f"From {round(score_before)}% to {round(score_after)}%.",
            url=reverse("project_detail", args=[project.pk]) + "#compliance",
            context=context,
        )

    @classmethod
    def runs_timed_out(cls, *, project, execution_ids, triggered_by_user_ids=()):
        """Runs nobody finished in time were marked as errors."""
        n = len(execution_ids)
        return cls._new(
            project=project,
            kind=Kind.RUN_TIMED_OUT,
            severity=Severity.WARNING,
            title=f"{n} standard run{'s' if n != 1 else ''} timed out",
            body="Nothing finished them in time. Run them again from the project page.",
            url=reverse("project_detail", args=[project.pk]),
            context=_run_context(execution_ids, None, triggered_by_user_ids),
        )

    @classmethod
    def connection_broken(
        cls, *, project, connection, execution_ids=(), trigger=None, triggered_by_user_ids=(),
    ):
        """A run could not be evaluated because the Git connection no longer
        works (expired or revoked). Links to where it is reconnected."""
        context = _run_context(execution_ids, trigger, triggered_by_user_ids)
        context["connection_id"] = str(connection.pk)
        return cls._new(
            project=project,
            subject=connection.display_name,
            kind=Kind.CONNECTION_BROKEN,
            severity=Severity.CRITICAL,
            title="Git connection broken",
            body=f"GitGrit could not read {project.name}. Reconnect it in workspace settings.",
            url=reverse("tenant_settings") + "#section-connections",
            context=context,
        )

    # Dependency map

    @classmethod
    def graph_failed(cls, *, project, error):
        """A dependency map that used to build failed to rebuild. The map is
        built by the workspace's AI model, so it links to that setting."""
        return cls._new(
            project=project,
            kind=Kind.GRAPH_FAILED,
            severity=Severity.WARNING,
            title="Dependency graph failed",
            body=first_line(error),
            url=reverse("tenant_settings") + "#section-llm",
            context={},
        )

    @classmethod
    def ai_provider_failed(cls, *, project, error):
        """The workspace's AI provider refused GitGrit (bad key, no credit, no
        access) while building ``project``'s map."""
        return cls._new(
            project=project,
            subject="AI provider",
            kind=Kind.AI_PROVIDER_FAILED,
            severity=Severity.CRITICAL,
            title="AI provider refused GitGrit",
            body=first_line(error),
            url=reverse("tenant_settings") + "#section-llm",
            context={},
        )

    # Workspace changes

    @classmethod
    def project_added(cls, *, project, actor):
        return cls._new(
            project=project,
            actor=actor,
            kind=Kind.PROJECT_ADDED,
            severity=Severity.INFO,
            title="Project added",
            body=f"{_display_name(actor)} added {project.name}.",
            url=reverse("project_detail", args=[project.pk]),
            context={},
        )

    @classmethod
    def project_removed(cls, *, tenant_id, project_name, actor):
        return cls._new(
            tenant_id=tenant_id,
            subject=project_name,
            actor=actor,
            kind=Kind.PROJECT_REMOVED,
            severity=Severity.INFO,
            title="Project removed",
            body=f"{_display_name(actor)} removed {project_name}.",
            url=reverse("project_list"),
            context={"project_name": project_name},
        )

    @classmethod
    def member_joined(cls, *, tenant_id, member, role, actor):
        return cls._new(
            tenant_id=tenant_id,
            subject=_display_name(member),
            actor=actor,
            kind=Kind.MEMBER_JOINED,
            severity=Severity.INFO,
            title="Member joined",
            body=f"{_display_name(actor)} added {_display_name(member)} as {role}.",
            url=reverse("tenant_settings") + "#section-members",
            context={"member_user_id": str(member.pk)},
        )

    @classmethod
    def member_removed(cls, *, tenant_id, member, actor):
        """Someone was removed from the workspace, or left it (``actor`` is
        then the member themselves)."""
        left = actor is not None and actor.pk == member.pk
        return cls._new(
            tenant_id=tenant_id,
            subject=_display_name(member),
            actor=actor,
            kind=Kind.MEMBER_REMOVED,
            severity=Severity.INFO,
            title="Member left" if left else "Member removed",
            body=(
                f"{_display_name(member)} left the workspace."
                if left
                else f"{_display_name(actor)} removed {_display_name(member)}."
            ),
            url=reverse("tenant_settings") + "#section-members",
            context={"member_user_id": str(member.pk)},
        )

    @classmethod
    def member_role_changed(cls, *, tenant_id, member, old_role, new_role, actor):
        return cls._new(
            tenant_id=tenant_id,
            subject=_display_name(member),
            actor=actor,
            kind=Kind.MEMBER_ROLE_CHANGED,
            severity=Severity.INFO,
            title="Role changed",
            body=f"{_display_name(actor)} made {_display_name(member)} {new_role} (was {old_role}).",
            url=reverse("tenant_settings") + "#section-members",
            context={"member_user_id": str(member.pk), "old_role": old_role, "new_role": new_role},
        )

    @classmethod
    def standard_changed(cls, *, standard, actor, activated=False):
        """A runnable standard's code was saved, or it was switched on. Either
        way it runs on its projects again, so scores may move."""
        verb = "activated" if activated else "changed"
        return cls._new(
            tenant_id=standard.tenant_id,
            subject=standard.name,
            actor=actor,
            kind=Kind.STANDARD_CHANGED,
            severity=Severity.INFO,
            title=f"Standard {verb}",
            body=f"{_display_name(actor)} {verb} {standard.name}. It runs on its projects again.",
            url=reverse("standard_detail", args=[standard.pk]),
            context={"standard_id": str(standard.pk), "activated": activated},
        )

    @classmethod
    def _new(
        cls, *, kind, severity, title, body, url, context, project=None, tenant_id=None,
        subject=None, actor=None,
    ):
        """Every notification names its ``subject`` (what the row is about: a
        project, a connection, a standard, a person), and the person behind it
        when there is one, so routing can leave them out."""
        base = {"subject": subject or (project.name if project else "")}
        if project is not None:
            base["project_id"] = str(project.pk)
            base["project_name"] = project.name
        if actor is not None:
            base["actor_user_id"] = str(actor.pk)
        title_max = cls._meta.get_field("title").max_length
        return cls(
            tenant_id=project.tenant_id if project is not None else tenant_id,
            kind=kind,
            severity=severity,
            title=title[:title_max],
            body=body,
            url=url,
            context={**base, **context},
        )


def _display_name(user) -> str:
    if user is None:
        return "Someone"
    return user.get_full_name() or user.email or user.username


def _run_context(execution_ids, trigger, triggered_by_user_ids):
    context = {"execution_ids": [str(e) for e in execution_ids]}
    if trigger:
        context["trigger"] = trigger
    if triggered_by_user_ids:
        context["triggered_by_user_ids"] = [str(u) for u in triggered_by_user_ids]
    return context


class InboxItem(models.Model):
    """One person's copy of a Notification in their inbox.

    Read state is personal, so it lives here and not on the Notification.
    Part of the Inbox aggregate (``app.domain.notifications.inbox``), which
    owns the rules for creating and reading items.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="inbox_items",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="inbox_items",
    )
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inbox_items"
        ordering = ["-created_at"]
        indexes = [
            # The bell: one user's unread items.
            models.Index(fields=["recipient", "read_at"], name="idx_inbox_item_unread"),
        ]

    def __str__(self):
        return f"{self.notification_id} → {self.recipient_id}"

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


class DeliveryLog(models.Model):
    """Did delivering a Notification on one channel work?

    The dispatcher writes one row per channel it tried. It skips channels
    that already have a SENT row, so a re-run after a crash never delivers
    twice; a FAILED row is the record of what went wrong.
    """

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="delivery_logs",
    )
    channel = models.CharField(max_length=50)
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_delivery_logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.notification_id} on {self.channel}: {self.status}"
