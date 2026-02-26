from django.urls import path

from app.views import RunPolicyView

urlpatterns = [
    path("run-policy/", RunPolicyView.as_view(), name="run-policy"),
]
