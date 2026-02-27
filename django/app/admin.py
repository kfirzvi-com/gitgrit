from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from app.domain.models import Membership, PlatformConnection, Project, Tenant, User


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
