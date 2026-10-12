from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from app.presentation.api import views

workspace_patterns = [
    path("projects/", views.ProjectListView.as_view(), name="api_projects"),
    path("projects/resolve/", views.ProjectResolveView.as_view(), name="api_project_resolve"),
    path(
        "projects/<uuid:project_id>/status/",
        views.ProjectStatusView.as_view(),
        name="api_project_status",
    ),
    path(
        "projects/<uuid:project_id>/standards/",
        views.ProjectStandardsView.as_view(),
        name="api_project_standards",
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
]

urlpatterns = [
    path("me/", views.MeView.as_view(), name="api_me"),
    path("workspaces/<uuid:workspace_id>/", include(workspace_patterns)),
    path("schema/", SpectacularAPIView.as_view(), name="api_schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api_schema"), name="api_docs"),
]
