"""When something is worth a notification: the decisions the notification
policies make, as pure functions of the event. Pure Python (no Django)."""

from __future__ import annotations

from app.domain.events import DependencyInferenceFailed, StandardRunFinished


def could_not_evaluate(event: StandardRunFinished) -> bool:
    """The run could not be evaluated at all: the job itself failed, or every
    standard in it errored. This outranks failing standards."""
    all_errored = event.errored > 0 and event.passed == 0 and event.failed == 0
    return bool(event.error) or all_errored


def standards_failing(event: StandardRunFinished) -> bool:
    """The run could be evaluated and left standards failing."""
    return event.failed > 0 and not could_not_evaluate(event)


def graph_broke(event: DependencyInferenceFailed) -> bool:
    """A dependency map that used to build failed. A map that never built (no
    AI model, say) would fail on every push, so it is not worth telling."""
    return event.had_worked_before
