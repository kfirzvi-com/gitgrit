from django.urls import path

from app.presentation.views.policy_views import (
    CreatePolicyView,
    EditPolicyView,
    PolicyDetailView,
    PolicyListView,
    delete_policy,
    run_policy_test,
    toggle_policy,
)
from app.presentation.views.project_views import (
    ProjectDetailView,
    ProjectListView,
    add_project_search,
    add_project_select,
    delete_project,
    retry_webhook,
    run_project_policies,
)
from app.presentation.views.stack_views import (
    CreateStackView,
    StackDetailView,
    StackListView,
    add_project_to_stack,
    delete_stack,
    remove_project_from_stack,
)
from app.presentation.views.tenant_views import (
    CreateTenantView,
    TenantSettingsView,
    add_connection,
    edit_connection_token,
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
        "tenants/connections/<uuid:connection_id>/edit/",
        edit_connection_token,
        name="edit_connection_token",
    ),
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
    path(
        "projects/<uuid:pk>/run-policies/",
        run_project_policies,
        name="run_project_policies",
    ),
    path(
        "projects/<uuid:pk>/retry-webhook/",
        retry_webhook,
        name="retry_webhook",
    ),
    # Stacks
    path("stacks/", StackListView.as_view(), name="stack_list"),
    path("stacks/new/", CreateStackView.as_view(), name="create_stack"),
    path("stacks/<uuid:pk>/", StackDetailView.as_view(), name="stack_detail"),
    path("stacks/<uuid:pk>/delete/", delete_stack, name="delete_stack"),
    path(
        "stacks/<uuid:pk>/projects/add/",
        add_project_to_stack,
        name="add_project_to_stack",
    ),
    path(
        "stacks/<uuid:stack_pk>/projects/<uuid:project_pk>/remove/",
        remove_project_from_stack,
        name="remove_project_from_stack",
    ),
    # Policies
    path("policies/", PolicyListView.as_view(), name="policy_list"),
    path("policies/new/", CreatePolicyView.as_view(), name="create_policy"),
    path("policies/<uuid:pk>/", PolicyDetailView.as_view(), name="policy_detail"),
    path("policies/<uuid:pk>/edit/", EditPolicyView.as_view(), name="edit_policy"),
    path("policies/<uuid:pk>/delete/", delete_policy, name="delete_policy"),
    path("policies/<uuid:pk>/toggle/", toggle_policy, name="toggle_policy"),
    path("policies/test/", run_policy_test, name="run_policy_test"),
]
