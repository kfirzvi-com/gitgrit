from django.urls import path

from app.presentation.views.access_views import (
    access_request_status,
    first_run_setup,
    no_workspace,
    resend_confirmation,
)
from app.presentation.views.staff_views import (
    access_request_list,
    access_request_tab,
    admin_dashboard,
    grant_superuser,
    review_access_request,
    revoke_superuser,
)

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
    project_history,
    run_on_branch,
    project_standards,
    retry_webhook,
    run_project_standards,
)
from app.presentation.views.stack_views import (
    CreateStackView,
    StackDetailView,
    StackListView,
    delete_stack,
    edit_stack,
    remove_component_from_stack,
    stack_components,
)
from app.presentation.views.tenant_views import (
    CreateTenantView,
    TenantSettingsView,
    add_connection,
    add_llm_provider,
    change_member_role,
    delete_workspace_view,
    edit_connection_token,
    edit_llm_provider,
    fetch_llm_models,
    invite_member,
    leave_support_view_view,
    leave_workspace,
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
    github_app_choose,
    github_app_confirm,
    github_app_install,
    github_app_install_new,
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
from app.presentation.views.notification_views import (
    mark_all_read,
    mark_read,
    mark_unread,
    notification_bell,
    notification_panel,
    open_notification,
)
from app.presentation.views.web_views import DashboardView, HomeView, refresh_map
from app.presentation.views.workspace_switcher_views import workspace_switcher_list
from app.presentation.views.token_views import (
    create_personal_token,
    create_workspace_token,
    revoke_personal_token,
    revoke_workspace_token,
)

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("setup/", first_run_setup, name="first_run_setup"),
    path("access/", access_request_status, name="access_request_status"),
    path("access/resend/", resend_confirmation, name="resend_confirmation"),
    path("staff/", admin_dashboard, name="admin_dashboard"),
    path("staff/access-requests/", access_request_list, name="access_request_list"),
    path("staff/access-requests/tab/", access_request_tab, name="access_request_tab"),
    path("staff/superusers/grant/", grant_superuser, name="grant_superuser"),
    path(
        "staff/superusers/<uuid:user_id>/revoke/",
        revoke_superuser,
        name="revoke_superuser",
    ),
    path(
        "staff/access-requests/<uuid:pk>/approve/",
        review_access_request,
        {"decision": "approve"},
        name="approve_access_request",
    ),
    path(
        "staff/access-requests/<uuid:pk>/reject/",
        review_access_request,
        {"decision": "reject"},
        name="reject_access_request",
    ),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("dashboard/refresh-map/", refresh_map, name="refresh_map"),
    path("notifications/panel/", notification_panel, name="notification_panel"),
    path("notifications/read-all/", mark_all_read, name="notifications_mark_all_read"),
    path("notifications/bell/", notification_bell, name="notification_bell"),
    path("notifications/<uuid:pk>/open/", open_notification, name="notification_open"),
    path("notifications/<uuid:pk>/read/", mark_read, name="notification_mark_read"),
    path("notifications/<uuid:pk>/unread/", mark_unread, name="notification_mark_unread"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("profile/disconnect/<str:provider>/", disconnect_social, name="disconnect_social"),
    # Tenant management
    path("tenants/switch/", switch_tenant, name="switch_tenant"),
    path("tenants/switcher/", workspace_switcher_list, name="workspace_switcher_list"),
    path("tenants/leave/", leave_workspace, name="leave_workspace"),
    path(
        "tenants/support/leave/",
        leave_support_view_view,
        name="leave_support_view",
    ),
    path("tenants/new/", CreateTenantView.as_view(), name="create_tenant"),
    path("tenants/settings/", TenantSettingsView.as_view(), name="tenant_settings"),
    path("tenants/delete/", delete_workspace_view, name="delete_workspace"),
    path("no-workspace/", no_workspace, name="no_workspace"),
    path("tenants/invite/", invite_member, name="invite_member"),
    path(
        "tenants/members/<uuid:membership_id>/remove/",
        remove_member,
        name="remove_member",
    ),
    path(
        "tenants/members/<uuid:membership_id>/role/",
        change_member_role,
        name="change_member_role",
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
    path(
        "tenants/github-app/choose/",
        github_app_choose,
        name="github_app_choose",
    ),
    path(
        "tenants/github-app/install-new/",
        github_app_install_new,
        name="github_app_install_new",
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
        "projects/<uuid:pk>/standards/",
        project_standards,
        name="project_standards",
    ),
    path(
        "projects/<uuid:pk>/history/",
        project_history,
        name="project_history",
    ),
    path(
        "projects/<uuid:pk>/history/run/",
        run_on_branch,
        name="run_on_branch",
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
    path("stacks/<uuid:pk>/edit/", edit_stack, name="edit_stack"),
    path("stacks/<uuid:pk>/components/", stack_components, name="stack_components"),
    path(
        "stacks/<uuid:stack_pk>/components/<uuid:component_pk>/remove/",
        remove_component_from_stack,
        name="remove_component_from_stack",
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
    path("profile/tokens/create/", create_personal_token, name="create_personal_token"),
    path(
        "profile/tokens/<uuid:token_id>/revoke/",
        revoke_personal_token,
        name="revoke_personal_token",
    ),
    path("tenants/tokens/create/", create_workspace_token, name="create_workspace_token"),
    path(
        "tenants/tokens/<uuid:token_id>/revoke/",
        revoke_workspace_token,
        name="revoke_workspace_token",
    ),
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
