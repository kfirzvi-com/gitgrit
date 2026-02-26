from __future__ import annotations

import logging

from app.domain.events import DomainEvent
from app.domain.policies import POLICIES
from app.infrastructure.sandbox.runner import SandboxRunner

logger = logging.getLogger(__name__)


class PolicyEngine:
    def __init__(self) -> None:
        self.runner = SandboxRunner()

    def run_for_event(self, event: DomainEvent) -> list[dict]:
        qualified = [
            p for p in POLICIES if event.event_type in p["events"]
        ]

        if not qualified:
            logger.info(
                "No policies matched event_type=%s for project=%s",
                event.event_type,
                event.external_project_id,
            )
            return []

        input_config = {
            "platform": event.platform,
            "project_id": event.external_project_id,
            "access_token": None,
        }

        results = []
        for policy in qualified:
            logger.info("Running policy %s for event %s", policy["id"], event.event_type)
            result = self.runner.run(policy["code"], input_config)
            result["policy_id"] = policy["id"]
            result["policy_name"] = policy["name"]
            results.append(result)

        return results
