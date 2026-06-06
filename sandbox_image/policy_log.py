"""Structured logging for policy execution, viewable when a policy fails.

A ``PolicyLogger`` is created per run and offered to the policy author (as the
``log`` parameter) and used internally by the ``llm`` object to record the
agentic process. It collects entries in memory — it never writes to stdout,
which is reserved for the JSON result. The runtime serializes ``entries`` into
the result so the host can persist and display them.

Each entry carries a full wall-clock timestamp (UTC, ISO 8601) so the log
reads like a timeline of when things happened.
"""
from __future__ import annotations

from datetime import datetime, timezone


class PolicyLogger:
    def __init__(self):
        self.entries = []

    def _log(self, level, message):
        self.entries.append(
            {
                "level": level,
                "message": str(message),
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            }
        )

    def __call__(self, message):
        self._log("info", message)

    def info(self, message):
        self._log("info", message)

    def warn(self, message):
        self._log("warning", message)

    def warning(self, message):
        self._log("warning", message)

    def error(self, message):
        self._log("error", message)

    def debug(self, message):
        self._log("debug", message)
