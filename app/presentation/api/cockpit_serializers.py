"""Shapes of the cockpit, AI usage, AI budget and stack endpoints, for the
OpenAPI document (and so the CLI's generated client)."""
from rest_framework import serializers

from app.domain.ai_usage import BudgetLevel, BudgetPeriod, UsageCategory
from app.presentation.api.serializers import LEVEL_CHOICES, ProjectRefSerializer, ScoreDisplaySerializer

PERIOD_CHOICES = [p.value for p in BudgetPeriod]
BUDGET_LEVEL_CHOICES = [b.value for b in BudgetLevel]
CATEGORY_CHOICES = [c.value for c in UsageCategory]
LIGHT_KEYS = ["failed", "below_a", "no_score", "ai_budget"]


# --- Overview -------------------------------------------------------------------


class HealthCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    failed = serializers.IntegerField(help_text="A Required standard failed.")
    needs_attention = serializers.IntegerField(help_text="Graded B to D, no score, or never checked.")
    healthy = serializers.IntegerField(help_text="Graded A+ or A.")
    checked = serializers.IntegerField(help_text="Projects with a score on record.")
    unchecked = serializers.IntegerField()


class WarningLightSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=LIGHT_KEYS)
    title = serializers.CharField()
    count = serializers.IntegerField()
    lit = serializers.BooleanField(help_text="A light turns on only when something needs action.")
    tone = serializers.ChoiceField(choices=LEVEL_CHOICES)


class AttentionProjectSerializer(serializers.Serializer):
    project = ProjectRefSerializer()
    tone = serializers.ChoiceField(choices=LEVEL_CHOICES, help_text="failed or needs_attention.")
    grade = ScoreDisplaySerializer(allow_null=True, help_text="Null when the project has no score.")
    why = serializers.CharField(help_text='e.g. "Lint failing", "No score: …", "Below par: Docs", "Not checked yet".')
    owner = serializers.CharField()
    stacks = serializers.ListField(child=serializers.CharField())


class LastCheckSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    project = ProjectRefSerializer()
    commit_sha = serializers.CharField()
    branch = serializers.CharField()


class ChecksByWeekSerializer(serializers.Serializer):
    this_week = serializers.IntegerField()
    last_week = serializers.IntegerField()
    peak = serializers.IntegerField(help_text="The busiest of the last four (rolling) weeks.")


class TrendPointSerializer(serializers.Serializer):
    day = serializers.DateField()
    healthy = serializers.IntegerField()
    total = serializers.IntegerField()


class OverviewSerializer(serializers.Serializer):
    health = HealthCountsSerializer()
    lights = WarningLightSerializer(many=True)
    needs_you = AttentionProjectSerializer(many=True, help_text="Failed first, each worst first.")
    last_check = LastCheckSerializer(allow_null=True, help_text="The newest score the counts read.")
    checks = ChecksByWeekSerializer()
    trend = TrendPointSerializer(many=True, help_text="Healthy projects, week by week, oldest first.")


# --- AI budgets -----------------------------------------------------------------


class ProviderRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class TokensSerializer(serializers.Serializer):
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()


class BudgetWindowSerializer(serializers.Serializer):
    starts = serializers.DateTimeField(help_text="When the current period began (workspace's local time).")
    last_day = serializers.DateField()
    resets = serializers.DateTimeField(help_text="When it starts over from zero.")


class BudgetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    provider = ProviderRefSerializer()
    model = serializers.CharField()
    period = serializers.ChoiceField(choices=PERIOD_CHOICES)
    input_limit = serializers.IntegerField(allow_null=True)
    output_limit = serializers.IntegerField(allow_null=True)
    low_at_percent = serializers.IntegerField(
        allow_null=True, help_text="Warn owners and admins when this much is left; null: only when used up."
    )
    stop_at_limit = serializers.BooleanField(help_text="Hold back new runs on the model once used up.")
    used = TokensSerializer(help_text="What the current period has used.")
    level = serializers.ChoiceField(choices=BUDGET_LEVEL_CHOICES, help_text="ok, near (low) or reached.")
    stops_runs = serializers.BooleanField()
    window = BudgetWindowSerializer()


class BudgetCreateSerializer(serializers.Serializer):
    provider_id = serializers.UUIDField()
    model = serializers.CharField()
    period = serializers.ChoiceField(choices=PERIOD_CHOICES)
    input_limit = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    output_limit = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    low_at_percent = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=99)
    stop_at_limit = serializers.BooleanField(required=False, default=False)


class BudgetUpdateSerializer(serializers.Serializer):
    """Only the fields sent change."""

    period = serializers.ChoiceField(choices=PERIOD_CHOICES, required=False)
    input_limit = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    output_limit = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    low_at_percent = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=99)
    stop_at_limit = serializers.BooleanField(required=False)


class BudgetableModelSerializer(serializers.Serializer):
    provider = ProviderRefSerializer()
    model = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField(), help_text="Roles that use it (GitGrit calls these).")
    has_budget = serializers.BooleanField()
    blocked = serializers.BooleanField(help_text="No budget: the model does not run.")


# --- AI usage -------------------------------------------------------------------


class ModelUsageSerializer(serializers.Serializer):
    model = serializers.CharField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    calls = serializers.IntegerField()
    blocked = serializers.BooleanField()
    budgets = BudgetSerializer(many=True)


class ProviderUsageSerializer(serializers.Serializer):
    id = serializers.UUIDField(allow_null=True, help_text="Null for usage of a deleted provider.")
    name = serializers.CharField()
    models = ModelUsageSerializer(many=True)


class CategoryUsageSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=CATEGORY_CHOICES)
    label = serializers.CharField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    calls = serializers.IntegerField()


class StandardUsageSerializer(serializers.Serializer):
    standard_id = serializers.UUIDField(allow_null=True)
    name = serializers.CharField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    runs = serializers.IntegerField()
    share = serializers.FloatField(help_text="Of all LLM-standard tokens in the period, 0-1.")
    heavy = serializers.BooleanField(help_text="Spends at least twice the median standard.")
    times_median = serializers.FloatField()


class BudgetSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    ok = serializers.IntegerField()
    near = serializers.IntegerField(help_text="At or under their low mark.")
    used_up = serializers.IntegerField()
    stopping = serializers.IntegerField(help_text="Used up and stopping runs.")


class AIUsageSerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=PERIOD_CHOICES)
    starts = serializers.DateTimeField()
    budgets = BudgetSummarySerializer()
    providers = ProviderUsageSerializer(many=True, help_text="Token counts are per model: models are priced apart.")
    categories = CategoryUsageSerializer(many=True)
    standards = StandardUsageSerializer(many=True, help_text="Biggest first.")


# --- Stacks ---------------------------------------------------------------------


class StackSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    project_count = serializers.IntegerField()
    failed = serializers.IntegerField()
    needs_attention = serializers.IntegerField()
    healthy = serializers.IntegerField()


class StackComponentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    path = serializers.CharField()
    project = ProjectRefSerializer()
    tone = serializers.ChoiceField(choices=LEVEL_CHOICES, help_text="Its repository's health.")
    grade = ScoreDisplaySerializer(allow_null=True)
    why = serializers.CharField()
    last_checked = serializers.DateTimeField(allow_null=True)


class StackDetailSerializer(StackSummarySerializer):
    standard_count = serializers.IntegerField()
    map_updated_at = serializers.DateTimeField(allow_null=True)
    map_refreshing = serializers.BooleanField()
    components = StackComponentSerializer(many=True, help_text="Worst first.")


class StackRefreshSerializer(serializers.Serializer):
    queued = serializers.IntegerField(help_text="Projects queued to rebuild the map from their main branch.")
