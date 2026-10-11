"""The notification domain.

This module is the vocabulary shared by every layer: the kinds, the
severities, and the one-line summary rule for a notification's detail text.
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
    PROJECT_CRITICAL = "project.critical"  # a project's score dropped to critical
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


BODY_MAX = 200
_TRACEBACK = "Traceback (most recent call last):"


def first_line(text: str) -> str:
    """One line of detail text. A traceback's useful line is its last one (the
    exception); any other text is summarized by its first line."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[-1] if any(_TRACEBACK in line for line in lines) else lines[0]
    return line[:BODY_MAX]
