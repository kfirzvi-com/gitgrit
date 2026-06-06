"""Structured logging for policy execution, viewable when a policy fails.

A ``PolicyLogger`` is created per run and offered to the policy author (as the
``log`` parameter) and used internally by the ``llm`` object to record the
agentic process. It collects entries in memory — it never writes to stdout,
which is reserved for the JSON result. The runtime serializes ``entries`` into
the result so the host can persist and display them.
"""
from __future__ import annotations

import time


class PolicyLogger:
    def __init__(self):
        self._t0 = time.monotonic()
        self.entries = []

    def _log(self, level, message):
        self.entries.append(
            {
                "level": level,
                "message": str(message),
                "t_ms": int((time.monotonic() - self._t0) * 1000),
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
