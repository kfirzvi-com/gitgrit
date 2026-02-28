from app.presentation.views.base_webhook import BaseWebhookView


class GitLabWebhookView(BaseWebhookView):
    platform = "gitlab"
