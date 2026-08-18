from __future__ import annotations

import logging
from typing import Literal

from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from app.application.standard_engine import StandardEngine
from app.domain.models import AuthMethod, PlatformConnection, Project
from app.infrastructure.parsers.registry import get_parser
from app.infrastructure.webhook_signatures import (
    verify_github_app_signature,
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

        # GitHub App delivery: a single shared App webhook. GitHub includes an
        # `installation` object on App-delivered events, which is how we tell
        # them apart from PAT per-repo webhooks (which have no such object and
        # keep using the per-project-secret path below).
        if (
            self.platform == "github"
            and settings.GITHUB_APP_ENABLED
            and isinstance(request.data, dict)
            and "installation" in request.data
        ):
            return self._handle_github_app_event(
                normalized_headers, raw_body, request.data, event
            )

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

        engine = StandardEngine()
        results = engine.run_for_event(event)

        return Response(
            {
                "event_type": event.event_type,
                "platform": event.platform,
                "external_project_id": event.external_project_id,
                "standards_run": len(results),
                "results": results,
            }
        )

    def _handle_github_app_event(
        self, headers: dict[str, str], body: bytes, payload: dict, event
    ) -> Response:
        """Handle a GitHub App-delivered webhook.

        Verifies the delivery against the App's single shared webhook secret
        (not a per-project secret), then dispatches by event type: lifecycle
        events (`installation`, `installation_repositories`) sync connections
        and projects; ordinary code events (`push`, `pull_request`) run standards
        for the App connection's projects.
        """
        if not verify_github_app_signature(body, headers.get("x-hub-signature-256")):
            logger.warning("GitHub App webhook signature rejected.")
            return Response({"detail": "Invalid signature."}, status=401)

        event_name = headers.get("x-github-event", "")
        installation = payload.get("installation", {}) or {}
        installation_id = installation.get("id")

        if event_name == "installation":
            return self._handle_installation_event(payload, installation_id)
        if event_name == "installation_repositories":
            return self._handle_installation_repositories(payload, installation_id)

        # Code events (push, pull_request, …): the App-secret signature already
        # authenticated the delivery, so no per-project secret is required. The
        # signature proves the delivery is GitHub's, not which installation it
        # is for, so scope the run to the connections holding this installation
        # — one shared secret must not reach a workspace this installation was
        # never granted anything by.
        if installation_id is None:
            logger.warning(
                "GitHub App %s delivery carried no installation id; ignoring.",
                event_name,
            )
            return Response(
                {"detail": "No installation id on an App delivery."}, status=400
            )

        engine = StandardEngine()
        results = engine.run_for_event(event, installation_id=installation_id)
        return Response(
            {
                "event_type": event.event_type,
                "platform": event.platform,
                "external_project_id": event.external_project_id,
                "standards_run": len(results),
                "results": results,
            }
        )

    def _handle_installation_event(
        self, payload: dict, installation_id: int | None
    ) -> Response:
        """On `installation.deleted`, remove the matching App connection(s);
        their projects cascade-delete with the connection."""
        action = payload.get("action")
        removed = 0
        if action == "deleted" and installation_id is not None:
            deleted, _ = PlatformConnection.objects.filter(
                platform="github",
                auth_method=AuthMethod.GITHUB_APP,
                installation_id=installation_id,
            ).delete()
            removed = deleted
        return Response(
            {"event": "installation", "action": action, "removed": removed}
        )

    def _handle_installation_repositories(
        self, payload: dict, installation_id: int | None
    ) -> Response:
        """React to repositories being added to / removed from an installation.

        Repositories *added* deliberately do not become projects. An
        installation's repository list is what GitGrit may reach; a workspace's
        project list is what that workspace chose to track, and those are not
        the same thing — several workspaces can hold one installation while
        each tracking a different subset of it. Creating the repo in all of
        them would overrule that choice on behalf of workspaces whose members
        did not make the change and have no way to opt out. They import what
        they want from Add Project, which already lists the installation's
        repositories.

        Repositories *removed* still drop the matching projects: access is
        genuinely gone, so leaving them would mean standards that can only
        fail. That deletion also removes their execution history, and reaches
        every workspace holding the installation — heavier than it should be
        for a change made elsewhere. Recording "we lost access" instead needs
        somewhere to record it, so it is left for its own piece of work.
        """
        connections = PlatformConnection.objects.filter(
            platform="github",
            auth_method=AuthMethod.GITHUB_APP,
            installation_id=installation_id,
        )
        removed_ids = [
            str(r.get("id")) for r in payload.get("repositories_removed", [])
        ]
        removed_count = 0
        if removed_ids:
            for conn in connections:
                deleted, _ = Project.objects.filter(
                    platform_connection=conn, external_id__in=removed_ids
                ).delete()
                removed_count += deleted
        return Response(
            {
                "event": "installation_repositories",
                # Repos the installation gained. Reported, not imported.
                "newly_available": len(payload.get("repositories_added", [])),
                "removed": removed_count,
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
