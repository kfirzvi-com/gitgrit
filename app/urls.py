from django.urls import include, path

from app.presentation.views.project_views import search_projects_api

urlpatterns = [
    path("webhooks/", include("app.presentation.urls")),
    path("projects/search/", search_projects_api, name="search_projects_api"),
]
