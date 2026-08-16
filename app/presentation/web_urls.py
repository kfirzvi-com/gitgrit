from django.urls import path

from app.presentation.views.standard_views import (
    CreateStandardView,
    EditStandardView,
    StandardDetailView,
    StandardExecutionDetailView,
    StandardListView,
    StandardVersionDetailView,
    delete_standard,
    revert_standard_version,
    run_standard_test,
    toggle_standard,
)
from app.presentation.views.project_views import (
    EditProjectView,
    ProjectDetailView,
    ProjectListView,
    add_project_search,
    add_project_select,
    delete_project,
    retry_webhook,
    run_project_standards,
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
    add_llm_provider,
    edit_connection_token,
    edit_llm_provider,
    fetch_llm_models,
    invite_member,
    remove_connection,
    remove_llm_provider,
    remove_member,
    reveal_connection_token,
    set_llm_role,
    switch_tenant,
    test_connection,
    test_llm_provider,
)
from app.presentation.views.github_app_views import (
    github_app_callback,
    github_app_confirm,
    github_app_install,
)
from app.presentation.views.badge_views import project_badge
from app.presentation.views.feedback_views import submit_feedback
from app.presentation.views.profile_views import ProfileView, disconnect_social
from app.presentation.views.marketplace_views import (
    MarketplaceBrowseView,
    MarketplacePackDetailView,
    MarketplaceStandardPreviewView,
    install_marketplace_pack,
    install_marketplace_standard,
    update_marketplace_standard,
)
from app.presentation.views.web_views import DashboardView, HomeView
from app.presentation.views.token_views import create_api_token, revoke_api_token

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("profile/disconnect/<str:provider>/", disconnect_social, name="disconnect_social"),
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
        "tenants/connections/<uuid:connection_id>/token/",
        reveal_connection_token,
        name="reveal_connection_token",
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
    # GitHub App install flow (gated behind GITHUB_APP_ENABLED)
    path(
        "tenants/github-app/install/",
        github_app_install,
        name="github_app_install",
    ),
    path(
        "tenants/github-app/callback/",
        github_app_callback,
        name="github_app_callback",
    ),
    path(
        "tenants/github-app/confirm/",
        github_app_confirm,
        name="github_app_confirm",
    ),
    # LLM providers & roles
    path("tenants/llm/providers/add/", add_llm_provider, name="add_llm_provider"),
    path(
        "tenants/llm/providers/<uuid:provider_id>/edit/",
        edit_llm_provider,
        name="edit_llm_provider",
    ),
    path(
        "tenants/llm/providers/<uuid:provider_id>/remove/",
        remove_llm_provider,
        name="remove_llm_provider",
    ),
    path(
        "tenants/llm/providers/<uuid:provider_id>/test/",
        test_llm_provider,
        name="test_llm_provider",
    ),
    path(
        "tenants/llm/providers/<uuid:provider_id>/fetch-models/",
        fetch_llm_models,
        name="fetch_llm_models",
    ),
    path("tenants/llm/roles/<str:role_name>/set/", set_llm_role, name="set_llm_role"),
    # Projects
    path("projects/", ProjectListView.as_view(), name="project_list"),
    path("projects/add/", add_project_select, name="add_project_select"),
    path(
        "projects/add/<uuid:connection_id>/",
        add_project_search,
        name="add_project_search",
    ),
    path("projects/<uuid:pk>/", ProjectDetailView.as_view(), name="project_detail"),
    path("projects/<uuid:pk>/edit/", EditProjectView.as_view(), name="edit_project"),
    path("projects/<uuid:pk>/delete/", delete_project, name="delete_project"),
    path(
        "projects/<uuid:pk>/run-standards/",
        run_project_standards,
        name="run_project_standards",
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
    # Standards
    path("standards/", StandardListView.as_view(), name="standard_list"),
    path("standards/new/", CreateStandardView.as_view(), name="create_standard"),
    path("standards/<uuid:pk>/", StandardDetailView.as_view(), name="standard_detail"),
    path("standards/<uuid:pk>/edit/", EditStandardView.as_view(), name="edit_standard"),
    path("standards/<uuid:pk>/delete/", delete_standard, name="delete_standard"),
    path("standards/<uuid:pk>/toggle/", toggle_standard, name="toggle_standard"),
    path("standards/test/", run_standard_test, name="run_standard_test"),
    path(
        "executions/<uuid:pk>/",
        StandardExecutionDetailView.as_view(),
        name="standard_execution_detail",
    ),
    path(
        "standards/versions/<uuid:pk>/",
        StandardVersionDetailView.as_view(),
        name="standard_version_detail",
    ),
    path(
        "standards/versions/<uuid:pk>/revert/",
        revert_standard_version,
        name="revert_standard_version",
    ),
    # API Tokens
    path("tenants/tokens/create/", create_api_token, name="create_api_token"),
    path("tenants/tokens/<uuid:token_id>/revoke/", revoke_api_token, name="revoke_api_token"),
    # Badges (public, unauthenticated)
    path("badge/<uuid:pk>.svg", project_badge, name="project_badge"),
    # Feedback
    path("feedback/", submit_feedback, name="submit_feedback"),
    # Marketplace
    path("marketplace/", MarketplaceBrowseView.as_view(), name="marketplace_browse"),
    path(
        "marketplace/packs/<slug:slug>/",
        MarketplacePackDetailView.as_view(),
        name="marketplace_pack_detail",
    ),
    path(
        "marketplace/packs/<slug:slug>/install/",
        install_marketplace_pack,
        name="install_marketplace_pack",
    ),
    path(
        "marketplace/standards/<slug:slug>/",
        MarketplaceStandardPreviewView.as_view(),
        name="marketplace_standard_preview",
    ),
    path(
        "marketplace/standards/<slug:slug>/install/",
        install_marketplace_standard,
        name="install_marketplace_standard",
    ),
    path(
        "marketplace/standards/<slug:slug>/update/",
        update_marketplace_standard,
        name="update_marketplace_standard",
    ),
]
