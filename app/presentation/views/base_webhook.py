from __future__ import annotations

import logging
from typing import Literal

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from app.application.policy_engine import PolicyEngine
from app.domain.models import Project
from app.infrastructure.parsers.registry import get_parser
from app.infrastructure.webhook_signatures import (
    verify_github_signature,
    verify_gitlab_token,
)

SignatureStatus = Literal["verified", "no_project", "unsecured", "rejected"]

logger = logging.getLogger(__name__)


class BaseWebhookView(APIView):
    """Base class for platform webhook endpoints."""

    platform: str  # set by subclasses

    def post(self, request: Request) -> Response:
        # Read raw body before any parser touches request.data — DRF parsers
        # consume the stream and `request.body` raises RawPostDataException
        # if read after.
        raw_body = request.body

        headers = {k.lower(): v for k, v in request.META.items() if k.startswith("HTTP_")}
        # Normalize Django's header mangling: HTTP_X_GITHUB_EVENT → x-github-event
        normalized_headers = {
            k.replace("http_", "").replace("_", "-"): v for k, v in headers.items()
        }

        parser = get_parser(self.platform)
        event = parser.parse(normalized_headers, request.data)

        signature_status = self._verify_signature(
            event.external_project_id, normalized_headers, raw_body
        )
        if signature_status == "rejected":
            logger.warning(
                "Webhook signature rejected: platform=%s project=%s",
                self.platform,
                event.external_project_id,
            )
            return Response({"detail": "Invalid signature."}, status=401)
        if signature_status == "unsecured":
            logger.warning(
                "Webhook accepted without signature verification — project has "
                "empty webhook_secret: platform=%s project=%s",
                self.platform,
                event.external_project_id,
            )

        logger.info(
            "Webhook received: platform=%s event_type=%s project=%s actor=%s sig=%s",
            event.platform,
            event.event_type,
            event.external_project_id,
            event.actor,
            signature_status,
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

    def _verify_signature(
        self, external_project_id: str, headers: dict[str, str], body: bytes
    ) -> SignatureStatus:
        """Verify the request signature against any project that registered this hook.

        Returns:
            "verified": a matching project's secret validated the request.
            "no_project": no project matches the external id — nothing to verify;
                caller continues and downstream lookup returns empty results.
            "unsecured": matching project(s) exist but all have empty webhook_secret
                (legacy projects predating signature verification). Caller continues
                but logs a warning so operators can backfill the secrets.
            "rejected": at least one matching project has a configured secret and
                none of them validate the request — caller MUST 401.
        """
        all_secrets = list(
            Project.objects.filter(
                platform=self.platform, external_id=external_project_id
            ).values_list("webhook_secret", flat=True)
        )
        if not all_secrets:
            return "no_project"

        secrets_to_try = [s for s in all_secrets if s]
        if not secrets_to_try:
            return "unsecured"

        if self.platform == "github":
            sig_header = headers.get("x-hub-signature-256")
            for secret in secrets_to_try:
                if verify_github_signature(secret, body, sig_header):
                    return "verified"
        elif self.platform == "gitlab":
            token_header = headers.get("x-gitlab-token")
            for secret in secrets_to_try:
                if verify_gitlab_token(secret, token_header):
                    return "verified"

        return "rejected"
