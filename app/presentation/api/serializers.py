"""Request validation and response shapes for the public API.

Response serializers mirror the dicts the application services return; they
exist so the OpenAPI document (and the SDK generated from it) is fully typed.
Views return the service dicts as-is.
"""
from rest_framework import serializers

EVENT_CHOICES = ["push", "pull_request", "tag"]


# --- Requests -------------------------------------------------------------

class StandardCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    code = serializers.CharField(
        trim_whitespace=False,
        help_text="Python source defining evaluate(project).",
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")
    events = serializers.ListField(
        child=serializers.ChoiceField(choices=EVENT_CHOICES), required=False, default=list
    )
    ref_pattern = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Regex matched against the branch or tag. Empty matches all.",
    )
    languages = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    labels = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, default=list
    )
    draft = serializers.BooleanField(required=False, default=False)


class StandardUpdateSerializer(serializers.Serializer):
    """PATCH body — only the fields sent are changed."""

    name = serializers.CharField(max_length=255, required=False)
    code = serializers.CharField(trim_whitespace=False, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    events = serializers.ListField(
        child=serializers.ChoiceField(choices=EVENT_CHOICES), required=False
    )
    ref_pattern = serializers.CharField(required=False, allow_blank=True)
    languages = serializers.ListField(child=serializers.CharField(), required=False)
    labels = serializers.ListField(child=serializers.CharField(max_length=100), required=False)
    draft = serializers.BooleanField(required=False)
    enabled = serializers.BooleanField(required=False)
    change_summary = serializers.CharField(required=False, default="Updated via API")


class StandardTestSerializer(serializers.Serializer):
    code = serializers.CharField(trim_whitespace=False)
    mock_input = serializers.DictField(
        required=False,
        default=dict,
        help_text=(
            "Mock project data: files [{path, content}], languages {name: pct}, "
            "members, contributors, default_branch, topics, metadata."
        ),
    )


class ValidateEditSerializer(serializers.Serializer):
    file_path = serializers.CharField()
    new_content = serializers.CharField(trim_whitespace=False, allow_blank=True)
    prior_content = serializers.CharField(
        trim_whitespace=False,
        allow_blank=True,
        allow_null=True,
        required=False,
        default=None,
        help_text="Current file content; omit or null for a new file.",
    )


# --- Responses ------------------------------------------------------------

class ProjectSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    platform = serializers.CharField()
    full_path = serializers.CharField()
    web_url = serializers.CharField()
    default_branch = serializers.CharField()
    lifecycle = serializers.CharField()
    languages = serializers.ListField(child=serializers.CharField())
    tags = serializers.ListField(child=serializers.CharField())


class ResolvedProjectSerializer(ProjectSerializer):
    matched_by = serializers.ChoiceField(choices=["full_path", "web_url"])


class ProjectNotFoundSerializer(serializers.Serializer):
    detail = serializers.CharField()
    candidates = serializers.ListField(
        child=serializers.CharField(), help_text="Up to 5 close full_path matches."
    )


class ProjectRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class OffenderSerializer(serializers.Serializer):
    standard_id = serializers.UUIDField()
    name = serializers.CharField()
    score = serializers.IntegerField(allow_null=True)
    message = serializers.CharField()
    last_run = serializers.DateTimeField()


class ProjectStatusSerializer(serializers.Serializer):
    project = ProjectRefSerializer()
    overall_score = serializers.FloatField(allow_null=True)
    grade = serializers.CharField(allow_null=True)
    total_standards = serializers.IntegerField()
    passed = serializers.IntegerField()
    failed = serializers.IntegerField()
    top_offenders = OffenderSerializer(many=True)


class LastExecutionSerializer(serializers.Serializer):
    score = serializers.IntegerField(allow_null=True)
    status = serializers.CharField()
    message = serializers.CharField()
    created_at = serializers.DateTimeField()


class ActiveStandardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    rules = serializers.DictField(
        help_text="Extracted enforcement rules: watched files, forbidden patterns, flags."
    )
    enabled = serializers.BooleanField()
    draft = serializers.BooleanField()
    labels = serializers.ListField(child=serializers.CharField())
    languages = serializers.ListField(child=serializers.CharField())
    last_execution = LastExecutionSerializer(allow_null=True)


class ViolationSerializer(serializers.Serializer):
    standard = serializers.CharField()
    standard_id = serializers.UUIDField()
    kind = serializers.CharField()
    value = serializers.CharField()
    matched_substring = serializers.CharField()
    snippet = serializers.CharField()


class ValidateEditResultSerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    introduced_violations = ViolationSerializer(many=True)
    pre_existing_violations_count = serializers.IntegerField()
    checked = serializers.IntegerField()
    skipped = serializers.IntegerField()
    notes = serializers.ListField(child=serializers.CharField())


class StandardSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    enabled = serializers.BooleanField()
    draft = serializers.BooleanField()
    labels = serializers.ListField(child=serializers.CharField())
    events = serializers.ListField(child=serializers.CharField())
    ref_pattern = serializers.CharField()
    languages = serializers.ListField(child=serializers.CharField())
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class ExecutionSerializer(serializers.Serializer):
    status = serializers.CharField()
    score = serializers.IntegerField(allow_null=True)
    message = serializers.CharField()
    project = serializers.CharField()
    created_at = serializers.DateTimeField()


class StandardDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    code = serializers.CharField()
    enabled = serializers.BooleanField()
    draft = serializers.BooleanField()
    labels = serializers.ListField(child=serializers.CharField())
    criteria = serializers.DictField()
    test_cases = serializers.JSONField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    recent_executions = ExecutionSerializer(many=True)


class RunsSummarySerializer(serializers.Serializer):
    projects = serializers.IntegerField()
    queued = serializers.IntegerField()
    already_running = serializers.IntegerField()
    message = serializers.CharField()


class StandardMutationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    runs = RunsSummarySerializer(
        required=False,
        help_text="Present when saving queued background runs on attached projects.",
    )


class StandardTestResultSerializer(serializers.Serializer):
    passed = serializers.BooleanField()
    score = serializers.IntegerField()
    message = serializers.CharField()
    details = serializers.DictField()


class UserRefSerializer(serializers.Serializer):
    id = serializers.CharField()
    username = serializers.CharField()
    email = serializers.CharField(allow_blank=True)


class WorkspaceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    role = serializers.CharField(
        allow_null=True,
        help_text="owner, admin or member; null for a workspace token, which has no user.",
    )


class MeSerializer(serializers.Serializer):
    token_type = serializers.ChoiceField(choices=["oauth", "personal_token", "workspace_token"])
    user = UserRefSerializer(allow_null=True)
    workspaces = WorkspaceSerializer(many=True)


# --- Health and commit checks ---------------------------------------------

LEVEL_CHOICES = ["healthy", "warning", "critical", "unknown"]


class RunCheckSerializer(serializers.Serializer):
    branch = serializers.CharField(
        required=False, help_text="Defaults to the project's default branch."
    )
    sha = serializers.RegexField(
        r"^[0-9a-f]{40}$",
        required=False,
        default="",
        help_text="Check this commit; omit to check the branch's latest commit.",
    )


class BranchSerializer(serializers.Serializer):
    name = serializers.CharField()
    is_default = serializers.BooleanField()


class CheckResultSerializer(serializers.Serializer):
    execution_id = serializers.UUIDField()
    standard_id = serializers.UUIDField(allow_null=True)
    standard_name = serializers.CharField()
    status = serializers.ChoiceField(choices=["running", "passed", "failed", "error", "skipped"])
    score = serializers.IntegerField(allow_null=True, help_text="Null while running.")
    message = serializers.CharField()
    branch = serializers.CharField()
    commit_sha = serializers.CharField(help_text="Empty until the run is pinned to a commit.")
    ran_at = serializers.DateTimeField()
    still_attached = serializers.BooleanField(
        required=False, help_text="Commit views only: whether the standard is still attached."
    )


class HealthSummaryFields(serializers.Serializer):
    score = serializers.IntegerField(allow_null=True)
    level = serializers.ChoiceField(choices=LEVEL_CHOICES)
    passed = serializers.IntegerField()
    failed = serializers.IntegerField()
    errored = serializers.IntegerField()


class ProjectHealthSerializer(HealthSummaryFields):
    project = ProjectRefSerializer()
    branch = serializers.CharField(
        allow_null=True, help_text="Null for the project's health (each standard's home branch)."
    )
    default_branch = serializers.CharField()
    running = serializers.BooleanField()
    results = CheckResultSerializer(many=True)


class StandardRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class CommitSerializer(HealthSummaryFields):
    sha = serializers.CharField()
    title = serializers.CharField()
    author = serializers.CharField()
    date = serializers.DateTimeField(allow_null=True)
    url = serializers.CharField()
    checked = serializers.BooleanField()
    running = serializers.IntegerField(help_text="Checks still running on this commit.")
    results = CheckResultSerializer(many=True)
    not_run = StandardRefSerializer(
        many=True, help_text="Standards that apply now but did not run on this commit."
    )


class CommitPageSerializer(serializers.Serializer):
    branch = serializers.CharField()
    page = serializers.IntegerField()
    has_more = serializers.BooleanField()
    commits = CommitSerializer(many=True)


class RunCheckResultSerializer(serializers.Serializer):
    branch = serializers.CharField()
    commit_sha = serializers.CharField(
        allow_null=True, help_text="Null when the platform could not resolve the head yet."
    )
    queued = serializers.IntegerField()
    already_running = serializers.IntegerField()
    message = serializers.CharField()
