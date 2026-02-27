from django.urls import path

from app.presentation.views.project_views import (
    ProjectDetailView,
    ProjectListView,
    add_project_search,
    add_project_select,
    delete_project,
)
from app.presentation.views.tenant_views import (
    CreateTenantView,
    TenantSettingsView,
    add_connection,
    invite_member,
    remove_connection,
    remove_member,
    switch_tenant,
    test_connection,
)
from app.presentation.views.web_views import DashboardView, HomeView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    # Tenant management
    path("tenants/switch/", switch_tenant, name="switch_tenant"),
    path("tenants/new/", CreateTenantView.as_view(), name="create_tenant"),
    path("tenants/settings/", TenantSettingsView.as_view(), name="tenant_settings"),
    path("tenants/invite/", invite_member, name="invite_member"),
    path(
        "tenants/members/<uuid:membership_id>/remove/",
        remove_member,
        name="remove_member",
    ),
    # Platform connections
    path("tenants/connections/add/", add_connection, name="add_connection"),
    path(
        "tenants/connections/<uuid:connection_id>/remove/",
        remove_connection,
        name="remove_connection",
    ),
    path(
        "tenants/connections/<uuid:connection_id>/test/",
        test_connection,
        name="test_connection",
    ),
    # Projects
    path("projects/", ProjectListView.as_view(), name="project_list"),
    path("projects/add/", add_project_select, name="add_project_select"),
    path(
        "projects/add/<uuid:connection_id>/",
        add_project_search,
        name="add_project_search",
    ),
    path("projects/<uuid:pk>/", ProjectDetailView.as_view(), name="project_detail"),
    path("projects/<uuid:pk>/delete/", delete_project, name="delete_project"),
]
