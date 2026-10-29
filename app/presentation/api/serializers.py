"""Request validation and response shapes for the public API.

Response serializers mirror the dicts the application services return; they
exist so the OpenAPI document (and the SDK generated from it) is fully typed.
Views return the service dicts as-is.
"""
from rest_framework import serializers

from app.domain import importance
from app.domain.scoring import CommitScoreOutcome
from app.domain.score_representation import ScoreTone
from app.presentation import importance_text

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


# --- Responses ------------------------------------------------------------

class ProjectSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    platform = serializers.CharField(help_text="github, gitlab, or artifact.")
    external_id = serializers.CharField(
        help_text="The platform's id for the repository; for an artifact project, the caller's own."
    )
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


# A project's health and a score's colour: healthy (A+, A), needs_attention
# (B to D), failed (a Required standard failed), unknown (no score).
LEVEL_CHOICES = [tone.value for tone in ScoreTone]

# A commit's one outcome, decided in this order: checking, no_score, failed,
# scored (scoring.CommitScoreOutcome).
OUTCOME_CHOICES = [outcome.value for outcome in CommitScoreOutcome]
OUTCOME_HELP = (
    "checking: a run on the commit is still going; "
    "no_score: an expected standard errored or never ran (Required too), so nothing is reported; "
    "failed: every standard ran and a Required one failed (no value, it reads F); "
    "scored: every standard ran, none Required failed: the importance-weighted average, 0-100, even 0."
)


class ScoreDisplaySerializer(serializers.Serializer):
    """A score as the app shows it, so API clients can show it the same way."""

    text = serializers.CharField(help_text='What the app shows, e.g. "B"; "—" when there is no score.')
    tone = serializers.ChoiceField(choices=LEVEL_CHOICES, help_text="Its health: healthy, needs_attention, failed or unknown.")
    spoken = serializers.CharField(help_text='The same in words, e.g. "Score 82 out of 100".')


class StandardsProgressSerializer(serializers.Serializer):
    expected = serializers.IntegerField(help_text="Standards the commit's newest check expects.")
    finished = serializers.IntegerField(help_text="Of those, how many have a finished result.")


class ProjectStatusSerializer(serializers.Serializer):
    project = ProjectRefSerializer()
    overall_score = serializers.FloatField(
        allow_null=True,
        help_text="The project's score: its default branch's newest commit's. "
        "Null when that commit failed (see outcome), has no score, or is still being checked.",
    )
    outcome = serializers.ChoiceField(choices=OUTCOME_CHOICES, allow_null=True, help_text=OUTCOME_HELP)
    grade = serializers.CharField(
        help_text="The score as the app shows it (same as display.text)."
    )
    display = ScoreDisplaySerializer()
    score_failed = serializers.BooleanField(
        help_text="Every standard ran and a Required one failed: the project failed and has no score."
    )
    reason = serializers.CharField(help_text="Why the project failed; empty otherwise.")
    commit_sha = serializers.CharField(allow_null=True, help_text="The commit the score is from.")
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
    importance = serializers.ChoiceField(
        choices=importance.choices(),
        help_text="How much the standard matters to this project: " + importance_text.help_text(),
    )
    rules = serializers.DictField(
        help_text="Extracted enforcement rules: watched files, forbidden patterns, flags."
    )
    enabled = serializers.BooleanField()
    draft = serializers.BooleanField()
    labels = serializers.ListField(child=serializers.CharField())
    languages = serializers.ListField(child=serializers.CharField())
    last_execution = LastExecutionSerializer(allow_null=True)


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
    score_display = ScoreDisplaySerializer()
    passed = serializers.IntegerField()
    failed = serializers.IntegerField()
    errored = serializers.IntegerField()


class ScoredCommitRefSerializer(serializers.Serializer):
    sha = serializers.CharField()
    branch = serializers.CharField()
    committed_at = serializers.DateTimeField(allow_null=True)


class CommitScoreSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(
        choices=OUTCOME_CHOICES, help_text="The one answer: read this first. " + OUTCOME_HELP
    )
    value = serializers.IntegerField(
        allow_null=True, help_text="The score, 0-100; only when outcome is scored, null otherwise."
    )
    reason = serializers.CharField(
        help_text='Why it failed ("X failing") or has no score ("X errored", "Y not run"); empty otherwise.'
    )
    display = ScoreDisplaySerializer()
    standards = StandardsProgressSerializer()
    commit = ScoredCommitRefSerializer()


class ProjectHealthSerializer(HealthSummaryFields):
    project = ProjectRefSerializer()
    branch = serializers.CharField(
        allow_null=True, help_text="Null for the project's health (its default branch)."
    )
    default_branch = serializers.CharField()
    commit_score = CommitScoreSerializer(
        allow_null=True,
        help_text="The branch's newest commit, whatever its outcome (checking, no_score, failed, scored); "
        "null when nothing on it was checked.",
    )
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
    commit_score = CommitScoreSerializer(allow_null=True, help_text="Null when the commit was never checked.")
    results = CheckResultSerializer(many=True)
    expected_but_never_ran = StandardRefSerializer(
        many=True, help_text="Standards this commit's check expected that never ran on it."
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


# --- Connections, repositories, project management ------------------------

class ConnectionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()
    platform = serializers.CharField()
    auth_method = serializers.ChoiceField(choices=["pat", "github_app"])
    base_url = serializers.CharField(allow_blank=True)
    account_login = serializers.CharField(allow_null=True, help_text="GitHub App connections: the org or user.")
    created_at = serializers.DateTimeField()


class ConnectionCreateSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=["github", "gitlab"])
    access_token = serializers.CharField(trim_whitespace=True)
    display_name = serializers.CharField(required=False, allow_blank=True, default="")
    base_url = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="Self-hosted GitLab/GitHub Enterprise. Empty for the public service.",
    )


class RepositorySerializer(serializers.Serializer):
    external_id = serializers.CharField()
    name = serializers.CharField()
    full_path = serializers.CharField()
    web_url = serializers.CharField()
    default_branch = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True, allow_blank=True)
    already_added = serializers.BooleanField()


class ProjectCreateSerializer(serializers.Serializer):
    """Either kind of project: a repository from a connection (the default),
    or an artifact project, whose commits are uploaded builds."""

    type = serializers.ChoiceField(
        choices=["repository", "artifact"], required=False, default="repository",
        help_text="`repository`: add a repository a connection reaches. `artifact`: create "
        "a project whose commits are build archives you upload (`POST projects/<id>/commits/`).",
    )
    repository = serializers.CharField(
        required=False, help_text="`repository` only (required): the repository's path (`org/repo`) or platform id."
    )
    connection_id = serializers.UUIDField(
        required=False,
        help_text="`repository` only: which connection reaches it. Optional when only one connection can.",
    )
    lifecycle = serializers.CharField(required=False, default="development")
    owner = serializers.CharField(required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=255, required=False, help_text="`artifact` only (required).")
    external_id = serializers.CharField(
        max_length=255, required=False,
        help_text="`artifact` only (required): your own id for the project. Creating it again with "
        "the same id returns the existing project (200).",
    )
    stack = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
        help_text="`artifact` only: the stack to put it in, found by name or created.",
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")
    standards = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_null=True, default=None,
        help_text="Workspace standards to attach; none when omitted.",
    )

    def validate(self, data):
        needed = ["name", "external_id"] if data["type"] == "artifact" else ["repository"]
        missing = {f: "This field is required." for f in needed if not data.get(f, "").strip()}
        if missing:
            raise serializers.ValidationError(missing)
        return data


class ProjectUpdateSerializer(serializers.Serializer):
    """PATCH body — only the fields sent are changed."""

    lifecycle = serializers.CharField(required=False)
    owner = serializers.CharField(required=False, allow_blank=True)


class AttachedStandardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    enabled = serializers.BooleanField()
    draft = serializers.BooleanField()


class ProjectDetailSerializer(ProjectSerializer):
    owner = serializers.CharField(allow_blank=True)
    connection_id = serializers.UUIDField()
    webhook = serializers.ChoiceField(
        choices=["app", "active", "missing", "none"],
        help_text="`app`: events come through the GitHub App; `missing`: re-register from the project page; "
        "`none`: an artifact project, whose commits are uploaded instead.",
    )
    standards = AttachedStandardSerializer(many=True, help_text="Every attached standard, runnable or not.")


class ProjectCreatedSerializer(ProjectDetailSerializer):
    runs = RunsSummarySerializer(allow_null=True, help_text="The first run, when standards were attached.")


class StandardIdsSerializer(serializers.Serializer):
    standards = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)


class ImportanceSerializer(serializers.Serializer):
    """PATCH body for an attached standard."""

    importance = serializers.ChoiceField(
        choices=importance.choices(),
        help_text=importance_text.help_text(),
    )


class AttachedStandardImportanceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    importance = serializers.ChoiceField(choices=importance.choices())


class ProjectStandardsChangeSerializer(serializers.Serializer):
    standards = AttachedStandardSerializer(many=True)
    runs = RunsSummarySerializer(allow_null=True)


class StandardEnabledSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    enabled = serializers.BooleanField()
    runs = RunsSummarySerializer(allow_null=True, help_text="Queued on its projects when turned on.")


# --- Marketplace ------------------------------------------------------------

class MarketplaceStandardSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    version = serializers.IntegerField()
    labels = serializers.ListField(child=serializers.CharField())
    installed_standard_id = serializers.UUIDField(
        allow_null=True, help_text="This workspace's copy, when installed."
    )
    update_available = serializers.BooleanField()


class MarketplacePackSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField(allow_blank=True)
    standards = MarketplaceStandardSerializer(many=True)


class MarketplaceSerializer(serializers.Serializer):
    packs = MarketplacePackSerializer(many=True)
    standards = MarketplaceStandardSerializer(many=True)


class InstalledStandardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    created = serializers.BooleanField(help_text="False when the workspace already had it.")


class PackInstallSerializer(serializers.Serializer):
    pack = serializers.CharField()
    installed = InstalledStandardSerializer(many=True)
    skipped = InstalledStandardSerializer(many=True, help_text="Already in the workspace.")


class MarketplaceUpdateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    version = serializers.IntegerField()
    runs = RunsSummarySerializer(allow_null=True)
# --- Artifact projects --------------------------------------------------------

class CommitUploadSerializer(serializers.Serializer):
    archive = serializers.FileField(help_text="The project's files as a .zip or .tar.gz.")
    message = serializers.CharField(
        required=False, allow_blank=True, default="", trim_whitespace=False,
        help_text="The commit message; its first line is the title.",
    )
    branch = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="",
        help_text="Defaults to the project's default branch. Standards' Branch/Tag "
        "Filter matches it.",
    )


class UploadedCommitSerializer(serializers.Serializer):
    sha = serializers.CharField(
        help_text="The archive's content hash; poll `commits/<sha>/` for its checks."
    )
    message = serializers.CharField()
    branch = serializers.CharField()
    author = serializers.CharField()
    size = serializers.IntegerField()
    file_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class CommitUploadResultSerializer(serializers.Serializer):
    commit = UploadedCommitSerializer()
    created = serializers.BooleanField(
        help_text="False when the same archive was uploaded before (it is checked again)."
    )
    queued = serializers.IntegerField()
    message = serializers.CharField(help_text="What was queued, in a sentence.")
