import secrets
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

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
    access_token = EncryptedCharField(max_length=1024)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_connections"

    def __str__(self):
        return f"{self.display_name} ({self.platform})"

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
    # Frameworks/libraries/tools inferred by the LLM (e.g. Next.js, FastAPI,
    # Terraform). Merged + deduped with `languages` to form the node's tech
    # labels, so libraries show here rather than as separate graph nodes.
    inferred_technologies = models.JSONField(default=list, blank=True)
    # LLM dependency-inference status (drives the dashboard "regenerating…" hint).
    deps_status = models.CharField(
        max_length=10,
        choices=DepsStatus.choices,
        default=DepsStatus.NONE,
    )
    deps_analyzed_at = models.DateTimeField(null=True, blank=True)
    deps_error = models.TextField(blank=True, default="")
    stacks = models.ManyToManyField(
        "Stack",
        through="ProjectStack",
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


class ProjectStack(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="project_stacks",
    )
    stack = models.ForeignKey(
        Stack,
        on_delete=models.CASCADE,
        related_name="project_stacks",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "project_stacks"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "stack"], name="unique_project_stack"
            ),
        ]

    def __str__(self):
        return f"{self.project} — {self.stack}"


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


class ProjectDependency(models.Model):
    """A directed dependency between two projects in a workspace.

    Renders as an edge in the per-stack architecture diagram (source depends
    on target). When the two projects live in different stacks the edge
    crosses a stack boundary — that's how the stack view surfaces which of a
    stack's projects are public-facing (consumed from outside) and which
    reach out to projects in other stacks. Maintained by an LLM as projects
    change; ``label`` is the optional edge caption.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="project_dependencies",
    )
    source = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="dependencies_out",
    )
    target = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="dependencies_in",
    )
    label = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "project_dependencies"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target"], name="unique_project_dependency"
            ),
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")),
                name="project_dependency_no_self_loop",
            ),
        ]

    def __str__(self):
        return f"{self.source} → {self.target}"


class ExternalDependency(models.Model):
    """A relationship between a workspace project and a system outside the
    workspace.

    Direction distinguishes the two roles (both inferred by inspecting the
    project's repo):
      * ``OUTBOUND`` — the project depends on an external service/provider
        (e.g. Stripe, Auth0). Rendered at the bottom of the stack diagram.
      * ``INBOUND`` — an external consumer depends on the project (e.g. a
        public API client, a partner system, external webhook senders).
        Rendered at the top (we must preserve its API).

    Unlike ProjectDependency (which links two workspace projects), the other
    end here is outside the workspace. Maintained by an LLM as projects change.
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
    project = models.ForeignKey(
        Project,
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
                fields=["project", "name", "direction"],
                name="unique_external_dependency",
            ),
        ]

    def __str__(self):
        arrow = "←" if self.direction == self.Direction.INBOUND else "→"
        return f"{self.project} {arrow} {self.name}"


class InfrastructureComponent(models.Model):
    """A self-operated datastore/queue/cache/storage a project owns.

    These are stack-INTERNAL components (a service abstracts its own
    databases), not external services — rendered as internal nodes inside the
    stack diagram, not on the workspace graph. Per-project: two services with
    their own Postgres are two separate components. Maintained by an LLM.
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
    project = models.ForeignKey(
        Project,
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
                fields=["project", "name"], name="unique_infrastructure_component"
            ),
        ]

    def __str__(self):
        return f"{self.project} ⟐ {self.name}"


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


class PolicyLabel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="policy_labels",
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "policy_labels"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="unique_label_per_tenant",
            ),
        ]

    def __str__(self):
        return self.name


class Policy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="policies",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    code = models.TextField(
        default='def evaluate(project):\n    return {"passed": True, "score": 100, "message": "OK", "details": {}}\n'
    )
    criteria = models.JSONField(default=dict, blank=True)
    test_cases = models.JSONField(default=list, blank=True)
    labels = models.ManyToManyField(PolicyLabel, related_name="policies", blank=True)
    source_marketplace_policy = models.ForeignKey(
        "MarketplacePolicy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="installed_policies",
    )
    source_version = models.IntegerField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    draft = models.BooleanField(default=False)
    ordinal = models.IntegerField(default=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "policies"
        ordering = ["ordinal", "name"]

    def __str__(self):
        return self.name


class PolicyVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    policy = models.ForeignKey(
        Policy,
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
        db_table = "policy_versions"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "version"],
                name="unique_policy_version",
            ),
        ]

    def __str__(self):
        return f"{self.policy.name} v{self.version}"


class MarketplacePolicy(models.Model):
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
        db_table = "marketplace_policies"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} v{self.version}"


class MarketplacePack(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=10, blank=True, default="")
    policies = models.ManyToManyField(
        MarketplacePolicy, related_name="packs", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "marketplace_packs"
        ordering = ["name"]

    def __str__(self):
        return self.name


class PolicyExecution(models.Model):
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
        related_name="policy_executions",
    )
    policy = models.ForeignKey(
        Policy,
        on_delete=models.SET_NULL,
        null=True,
        related_name="executions",
    )
    policy_name = models.CharField(max_length=255)
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
    # execution detail page to help debug why a policy failed.
    logs = models.JSONField(default=list, blank=True)
    triggered_by = models.CharField(max_length=255, blank=True, default="")
    triggered_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="policy_executions",
    )
    ref = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "policy_executions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["project", "-created_at"],
                name="idx_policyexec_project_date",
            ),
            models.Index(
                fields=["policy", "-created_at"],
                name="idx_policyexec_policy_date",
            ),
        ]

    def __str__(self):
        return f"{self.policy_name} — {self.status} ({self.project})"


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
