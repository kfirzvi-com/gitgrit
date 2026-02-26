from django.urls import include, path

from app.views import RunPolicyView

urlpatterns = [
    path("run-policy/", RunPolicyView.as_view(), name="run-policy"),
    path("webhooks/", include("app.webhooks.urls")),
]
