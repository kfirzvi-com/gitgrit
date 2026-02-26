from django.urls import path

from app.presentation.views.tenant_views import (
    CreateTenantView,
    TenantSettingsView,
    invite_member,
    remove_member,
    switch_tenant,
)
from app.presentation.views.web_views import DashboardView, HomeView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("tenants/switch/", switch_tenant, name="switch_tenant"),
    path("tenants/new/", CreateTenantView.as_view(), name="create_tenant"),
    path("tenants/settings/", TenantSettingsView.as_view(), name="tenant_settings"),
    path("tenants/invite/", invite_member, name="invite_member"),
    path(
        "tenants/members/<uuid:membership_id>/remove/",
        remove_member,
        name="remove_member",
    ),
]
