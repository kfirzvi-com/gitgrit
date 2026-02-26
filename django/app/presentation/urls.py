from django.urls import path

from app.presentation.views import GitHubWebhookView, GitLabWebhookView

urlpatterns = [
    path("github/", GitHubWebhookView.as_view(), name="webhook-github"),
    path("gitlab/", GitLabWebhookView.as_view(), name="webhook-gitlab"),
]
