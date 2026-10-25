"""The notification domain.

This module is the vocabulary shared by every layer: the kinds, the
severities, and the plain-language reasons shown instead of raw error text.
Pure Python (no Django), so the models, the policies and tests can import it
from anywhere. Alongside it:

* ``notification_rules`` — when something is worth a notification (pure);
* ``notification_routing`` — who hears each kind, and on which channels;
* ``channels`` — the ``Channel`` port and the inbox adapter;
* ``inbox`` — the Inbox aggregate: one person's notifications and the
  reading rules.

The ``Notification``, ``InboxItem`` and ``DeliveryLog`` models live in
``app.domain.models`` with the other models.
"""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Kind:
    """The kinds of notification GitGrit raises."""

    # Runs
    RUN_FAILED = "run.failed"  # GitGrit could not evaluate a project
    STANDARDS_FAILING = "standards.failing"  # a run left standards failing
    PROJECT_CRITICAL = "project.critical"  # a run failed the project (a Required standard failed)
    RUN_TIMED_OUT = "run.timed_out"  # runs nobody finished were expired
    CONNECTION_BROKEN = "connection.broken"  # the Git connection stopped working
    # Dependency map
    GRAPH_FAILED = "graph.failed"  # a dependency map that used to build broke
    AI_PROVIDER_FAILED = "ai_provider.failed"  # the AI provider refused GitGrit
    # Workspace changes
    PROJECT_ADDED = "project.added"
    PROJECT_REMOVED = "project.removed"
    MEMBER_JOINED = "member.joined"
    MEMBER_REMOVED = "member.removed"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    STANDARD_CHANGED = "standard.changed"


# Detail text longer than this is cut.
BODY_MAX = 200


# Known causes, in the order they are checked, and how to say them to a
# person. Raw error text never reaches a notification: it stays on the page
# the notification links to (the run's details, the project, settings).
_PLAIN_REASONS = (
    (("credit balance", "insufficient_quota"), "The AI provider account is out of credit."),
    (("invalid x-api-key", "invalid api key", "api key"), "The AI provider rejected the API key."),
    (("bad credentials", "401", "unauthorized"), "GitHub or GitLab refused GitGrit's access token."),
    (("403", "forbidden"), "GitGrit is not allowed to read this repository."),
    (("404", "not found"), "The branch or repository no longer exists, or GitGrit can't see it."),
    (("rate limit", "429"), "The provider asked GitGrit to slow down. It tries again on the next push."),
    (("timed out", "timeout"), "It took too long and was stopped."),
)


def plain_reason(error: str) -> str | None:
    """A person-readable reason for a known error, or None when the error is
    not one we recognize."""
    text = (error or "").lower()
    for markers, reason in _PLAIN_REASONS:
        if any(marker in text for marker in markers):
            return reason
    return None
