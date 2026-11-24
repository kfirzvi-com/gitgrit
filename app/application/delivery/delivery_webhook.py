from __future__ import annotations

import logging
from typing import Callable

from app.application.delivery.delivery_sync_request import DeliverySyncRequest
from app.application.delivery.pull_request_refresh import PullRequestRefresh
from app.domain.delivery import PullRequestFacts
from app.domain.events import DomainEvent
from app.models import Project

# Reads a pull request out of a webhook payload; None when it has none.
PullRequestReader = Callable[[dict], PullRequestFacts | None]

logger = logging.getLogger(__name__)

# Platform events that may mean a deployment happened or finished.
DEPLOY_EVENTS = {"release", "deployment", "deployment_status", "workflow_run"}


class DeliveryWebhook:
    """Webhook events that change a project's delivery data ask for a sync
    straight away, so the Delivery tab is current within seconds instead of
    at the next scheduled sync: a release, a deployment's status, a finished
    workflow run, or a push to the default branch or the deploy branch
    (commits waiting to ship, and deploys for the branch strategies). A pull
    request event is recorded from its payload alone, with no API call."""

    @classmethod
    def receive(cls, event: DomainEvent, projects, read_pull_request: PullRequestReader | None = None) -> int:
        """Record the event's pull request, if any, and ask for a sync of
        each project the event touches; says how many syncs were asked for."""
        pull_request = read_pull_request(event.raw_payload) if read_pull_request and event.event_type == "pull_request" else None
        asked = 0
        for project in projects:
            if pull_request is not None:
                PullRequestRefresh.record(project, [pull_request])
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
