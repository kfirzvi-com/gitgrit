from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from app.domain.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Profile", {"fields": ("avatar_url",)}),
    )
    list_display = ("username", "email", "is_staff", "date_joined")
