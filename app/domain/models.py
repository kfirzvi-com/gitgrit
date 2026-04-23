import secrets
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


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
    access_token = models.CharField(max_length=512)
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


class Project(models.Model):
    class Lifecycle(models.TextChoices):
        DEVELOPMENT = "development", "Development"
        STAGING = "staging", "Staging"
        PRODUCTION = "production", "Production"
        MAINTENANCE = "maintenance", "Maintenance"
        DEPRECATED = "deprecated", "Deprecated"
        ARCHIVED = "archived", "Archived"

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


class APIToken(models.Model):
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
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "api_tokens"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.prefix}... ({self.tenant})"

    @classmethod
    def generate(cls) -> tuple["APIToken", str]:
        """Return an unsaved APIToken instance and the raw token string."""
        import hashlib
        raw = "grit_" + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        prefix = raw[:12]
        instance = cls(token_hash=token_hash, prefix=prefix)
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
