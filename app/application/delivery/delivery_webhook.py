from __future__ import annotations

import logging

from app.application.delivery.delivery_sync_request import DeliverySyncRequest
from app.domain.events import DomainEvent
from app.models import Project

logger = logging.getLogger(__name__)

# Platform events that may mean a deployment happened or finished.
DEPLOY_EVENTS = {"release", "deployment", "deployment_status", "workflow_run"}


class DeliveryWebhook:
    """Webhook events that change a project's delivery data ask for a sync
    straight away, so the Delivery tab is current within seconds instead of
    at the next scheduled sync: a release, a deployment's status, a finished
    workflow run, or a push to the default branch or the deploy branch
    (commits waiting to ship, and deploys for the branch strategies)."""

    @classmethod
    def receive(cls, event: DomainEvent, projects) -> int:
        """Ask for a sync of each project the event touches; says how many."""
        asked = 0
        for project in projects:
            if cls._touches(event, project):
                DeliverySyncRequest.send(project)
                asked += 1
        return asked

    @staticmethod
    def _touches(event: DomainEvent, project: Project) -> bool:
        if event.event_type in DEPLOY_EVENTS:
            return True
        if event.event_type != "push" or event.deleted or not event.ref:
            return False
        branch = event.ref.removeprefix("refs/heads/")
        delivery = getattr(project, "delivery", None)
        deploy_branch = delivery.deploy_branch if delivery else ""
        return branch in {project.default_branch, deploy_branch}
