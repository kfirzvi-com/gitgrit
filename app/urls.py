from django.urls import include, path

from app.presentation.views.project_views import search_projects_api
from app.presentation.views.setup_views import export_setup_file

urlpatterns = [
    path("webhooks/", include("app.presentation.urls")),
    path("projects/search/", search_projects_api, name="search_projects_api"),
    path("setup/<str:client>/", export_setup_file, name="export_setup_file"),
]
