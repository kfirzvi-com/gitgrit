from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from app.presentation.api import cockpit_views, llm_views, manage_views, views

workspace_patterns = [
    path("overview/", cockpit_views.OverviewView.as_view(), name="api_overview"),
    path("ai/usage/", cockpit_views.AIUsageView.as_view(), name="api_ai_usage"),
    path("ai/models/", cockpit_views.AIModelsView.as_view(), name="api_ai_models"),
    path("ai/budgets/", cockpit_views.AIBudgetsView.as_view(), name="api_ai_budgets"),
    path("ai/budgets/<uuid:budget_id>/", cockpit_views.AIBudgetView.as_view(), name="api_ai_budget"),
    path("llm/providers/", llm_views.LLMProvidersView.as_view(), name="api_llm_providers"),
    path("llm/providers/<uuid:provider_id>/", llm_views.LLMProviderView.as_view(), name="api_llm_provider"),
    path("llm/providers/<uuid:provider_id>/test/", llm_views.LLMProviderTestView.as_view(), name="api_llm_provider_test"),
    path(
        "llm/providers/<uuid:provider_id>/models/refresh/",
        llm_views.LLMModelsRefreshView.as_view(),
        name="api_llm_models_refresh",
    ),
    path("llm/roles/", llm_views.LLMRolesView.as_view(), name="api_llm_roles"),
    path("llm/roles/<str:role>/", llm_views.LLMRoleView.as_view(), name="api_llm_role"),
    path("stacks/", cockpit_views.StackListView.as_view(), name="api_stacks"),
    path("stacks/<uuid:stack_id>/", cockpit_views.StackDetailView.as_view(), name="api_stack"),
    path("stacks/<uuid:stack_id>/refresh/", cockpit_views.StackRefreshView.as_view(), name="api_stack_refresh"),
    path("connections/", manage_views.ConnectionListView.as_view(), name="api_connections"),
    path(
        "connections/<uuid:connection_id>/repositories/",
        manage_views.RepositoryListView.as_view(),
        name="api_connection_repositories",
    ),
    path("projects/", manage_views.ProjectsView.as_view(), name="api_projects"),
    path("projects/resolve/", views.ProjectResolveView.as_view(), name="api_project_resolve"),
    path(
        "projects/<uuid:project_id>/",
        manage_views.ProjectDetailView.as_view(),
        name="api_project",
    ),
    path(
        "projects/<uuid:project_id>/status/",
        views.ProjectStatusView.as_view(),
        name="api_project_status",
    ),
    path(
        "projects/<uuid:project_id>/standards/",
        manage_views.ProjectStandardsView.as_view(),
        name="api_project_standards",
    ),
    path(
        "projects/<uuid:project_id>/standards/<uuid:standard_id>/",
        manage_views.ProjectStandardView.as_view(),
        name="api_project_standard",
    ),
    path(
        "projects/<uuid:project_id>/branches/",
        views.ProjectBranchesView.as_view(),
        name="api_project_branches",
    ),
    path(
        "projects/<uuid:project_id>/health/",
        views.ProjectHealthView.as_view(),
        name="api_project_health",
    ),
    path(
        "projects/<uuid:project_id>/commits/",
        views.ProjectCommitsView.as_view(),
        name="api_project_commits",
    ),
    path(
        "projects/<uuid:project_id>/commits/<str:sha>/",
        views.ProjectCommitView.as_view(),
        name="api_project_commit",
    ),
    path(
        "projects/<uuid:project_id>/checks/",
        views.ProjectCheckView.as_view(),
        name="api_project_checks",
    ),
    path("standards/", views.StandardListView.as_view(), name="api_standards"),
    path("standards/test/", views.StandardTestView.as_view(), name="api_standard_test"),
    path(
        "standards/<uuid:standard_id>/",
        views.StandardDetailView.as_view(),
        name="api_standard_detail",
    ),
    path(
        "standards/<uuid:standard_id>/enable/",
        manage_views.StandardEnableView.as_view(),
        name="api_standard_enable",
    ),
    path(
        "standards/<uuid:standard_id>/disable/",
        manage_views.StandardDisableView.as_view(),
        name="api_standard_disable",
    ),
    path("marketplace/", manage_views.MarketplaceView.as_view(), name="api_marketplace"),
    path(
        "marketplace/packs/<slug:slug>/",
        manage_views.MarketplacePackView.as_view(),
        name="api_marketplace_pack",
    ),
    path(
        "marketplace/packs/<slug:slug>/install/",
        manage_views.MarketplacePackInstallView.as_view(),
        name="api_marketplace_pack_install",
    ),
    path(
        "marketplace/standards/<slug:slug>/install/",
        manage_views.MarketplaceStandardInstallView.as_view(),
        name="api_marketplace_standard_install",
    ),
    path(
        "marketplace/standards/<slug:slug>/update/",
        manage_views.MarketplaceStandardUpdateView.as_view(),
        name="api_marketplace_standard_update",
    ),
]

urlpatterns = [
    path("me/", views.MeView.as_view(), name="api_me"),
    path("workspaces/<uuid:workspace_id>/", include(workspace_patterns)),
    path("schema/", SpectacularAPIView.as_view(), name="api_schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api_schema"), name="api_docs"),
]
