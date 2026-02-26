from __future__ import annotations

import logging

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from app.application.policy_engine import PolicyEngine
from app.infrastructure.parsers.registry import get_parser

logger = logging.getLogger(__name__)


class BaseWebhookView(APIView):
    """Base class for platform webhook endpoints."""

    platform: str  # set by subclasses

    def post(self, request: Request) -> Response:
        headers = {k.lower(): v for k, v in request.META.items() if k.startswith("HTTP_")}
        # Normalize Django's header mangling: HTTP_X_GITHUB_EVENT → x-github-event
        normalized_headers = {
            k.replace("http_", "").replace("_", "-"): v for k, v in headers.items()
        }

        parser = get_parser(self.platform)
        event = parser.parse(normalized_headers, request.data)

        logger.info(
            "Webhook received: platform=%s event_type=%s project=%s actor=%s",
            event.platform,
            event.event_type,
            event.external_project_id,
            event.actor,
        )

        engine = PolicyEngine()
        results = engine.run_for_event(event)

        return Response(
            {
                "event_type": event.event_type,
                "platform": event.platform,
                "external_project_id": event.external_project_id,
                "policies_run": len(results),
                "results": results,
            }
        )
