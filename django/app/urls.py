from django.urls import include, path

urlpatterns = [
    path("webhooks/", include("app.presentation.urls")),
]
