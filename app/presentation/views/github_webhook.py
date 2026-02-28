from app.presentation.views.base_webhook import BaseWebhookView


class GitHubWebhookView(BaseWebhookView):
    platform = "github"
