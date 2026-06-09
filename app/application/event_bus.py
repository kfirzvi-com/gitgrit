"""A tiny synchronous in-process domain-event bus.

Application services ``publish`` events; handlers registered via ``subscribe``
react in-process. Handlers run within the publisher's transaction (so a handler
that defers a Procrastinate job is atomic with the domain write). A handler that
raises is logged and skipped — one misbehaving reaction must not break the
domain operation.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)

_subscribers: dict[type, list[Callable]] = defaultdict(list)


def subscribe(event_type: type, handler: Callable) -> None:
    if handler not in _subscribers[event_type]:
        _subscribers[event_type].append(handler)


def publish(event) -> None:
    for handler in _subscribers[type(event)]:
        try:
            handler(event)
        except Exception:
            logger.exception(
                "event handler %r failed for %s", handler, type(event).__name__
            )


def clear() -> None:
    """Reset all subscriptions (used by tests)."""
    _subscribers.clear()
