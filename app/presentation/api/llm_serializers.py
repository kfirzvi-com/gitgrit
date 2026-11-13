"""Shapes of the LLM provider and role endpoints. A provider's API key is
write-only: it is never returned."""
from rest_framework import serializers

from app.domain.models import LLMProviderType, LLMRole
from app.presentation.api.cockpit_serializers import ProviderRefSerializer

PROVIDER_TYPES = list(LLMProviderType.values)
ROLE_NAMES = list(LLMRole.Name.values)


class LLMProviderSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    provider_type = serializers.ChoiceField(choices=PROVIDER_TYPES)
    display_name = serializers.CharField()
    base_url = serializers.CharField(help_text="Empty for the provider's own endpoint.")
    models = serializers.ListField(child=serializers.CharField(), help_text="Models this key can use.")
    roles = serializers.ListField(child=serializers.ChoiceField(choices=ROLE_NAMES), help_text="Roles that use it.")
    created_at = serializers.DateTimeField()


class LLMProviderAddedSerializer(LLMProviderSerializer):
    note = serializers.CharField(
        help_text="Why no models were found (the provider's own words), when none were; else empty."
    )


class LLMProviderCreateSerializer(serializers.Serializer):
    provider_type = serializers.ChoiceField(choices=PROVIDER_TYPES)
    api_key = serializers.CharField(help_text="Stored encrypted; never returned.")
    display_name = serializers.CharField(required=False, allow_blank=True, help_text='Default: the type, e.g. "Anthropic".')
    base_url = serializers.CharField(required=False, allow_blank=True, help_text="A proxy or self-hosted endpoint.")


class LLMProviderUpdateSerializer(serializers.Serializer):
    """Only the fields sent change."""

    display_name = serializers.CharField(required=False)
    base_url = serializers.CharField(required=False, allow_blank=True)
    api_key = serializers.CharField(required=False, help_text="A new key; never returned.")
    models = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Replace the list by hand (when discovery finds none)."
    )


class LLMProviderTestSerializer(serializers.Serializer):
    ok = serializers.BooleanField(help_text="The provider accepted the key.")


class LLMModelsRefreshSerializer(serializers.Serializer):
    models = serializers.ListField(child=serializers.CharField(), help_text="Models found; the list is kept when none are.")
    note = serializers.CharField(help_text="Why none were found, when none were.")


class LLMRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ROLE_NAMES)
    label = serializers.CharField()
    provider = ProviderRefSerializer(allow_null=True, help_text="Null when the role is not set.")
    model = serializers.CharField(allow_null=True)
    has_budget = serializers.BooleanField(help_text="Budgets are an allow-list: without one the role's model never runs.")


class LLMRoleSetSerializer(serializers.Serializer):
    provider_id = serializers.UUIDField()
    model = serializers.CharField()
