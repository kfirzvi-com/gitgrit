from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from app.domain.models import (
    MarketplacePack,
    MarketplacePolicy,
    Membership,
    PlatformConnection,
    Policy,
    PolicyExecution,
    Project,
    ProjectStack,
    Stack,
    Tenant,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Profile", {"fields": ("avatar_url",)}),
    )
    list_display = ("username", "email", "is_staff", "date_joined")


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    fields = ("user", "role", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "role", "created_at")
    list_filter = ("role", "tenant")
    search_fields = ("user__username", "user__email", "tenant__name")


@admin.register(PlatformConnection)
class PlatformConnectionAdmin(admin.ModelAdmin):
    list_display = ("display_name", "tenant", "platform", "base_url", "created_at")
    list_filter = ("platform",)
    search_fields = ("display_name", "tenant__name")

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        # Don't show raw token in edit form
        if obj:
            return [f for f in fields if f != "access_token"]
        return fields


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "platform", "lifecycle", "full_path", "created_at")
    list_filter = ("platform", "lifecycle", "tenant")
    search_fields = ("name", "full_path")


@admin.register(Stack)
class StackAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "created_at")
    list_filter = ("tenant",)
    search_fields = ("name",)


@admin.register(ProjectStack)
class ProjectStackAdmin(admin.ModelAdmin):
    list_display = ("project", "stack", "created_at")
    list_filter = ("stack",)
    search_fields = ("project__name", "stack__name")


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "enabled", "draft", "ordinal", "created_at")
    list_filter = ("tenant", "enabled", "draft")
    search_fields = ("name",)


class MarketplacePolicyInline(admin.TabularInline):
    model = MarketplacePack.policies.through
    extra = 1


@admin.register(MarketplacePolicy)
class MarketplacePolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "version", "author", "updated_at")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(MarketplacePack)
class MarketplacePackAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "icon", "updated_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [MarketplacePolicyInline]
    exclude = ("policies",)


@admin.register(PolicyExecution)
class PolicyExecutionAdmin(admin.ModelAdmin):
    list_display = (
        "policy_name",
        "project",
        "event_type",
        "status",
        "score",
        "triggered_by",
        "created_at",
    )
    list_filter = ("status", "event_type")
    search_fields = ("policy_name", "project__name", "triggered_by")
    readonly_fields = (
        "id",
        "project",
        "policy",
        "policy_name",
        "event_type",
        "status",
        "score",
        "message",
        "details",
        "triggered_by",
        "ref",
        "created_at",
    )

    def has_add_permission(self, request):
        return False
