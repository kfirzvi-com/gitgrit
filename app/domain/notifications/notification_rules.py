"""When something is worth a notification: the decisions the notification
policies make, as pure functions of the facts. Pure Python (no Django)."""

from __future__ import annotations

from app.domain.events import DependencyInferenceFailed, StandardRunFinished
from app.domain.health import CRITICAL, UNKNOWN, level_from_score

# An AI provider answers with these when the key is wrong (401), the account
# has no credit (402) or the key may not use the model (403).
_PROVIDER_REFUSALS = frozenset({401, 402, 403})
_PROVIDER_REFUSAL_TEXT = ("credit balance", "insufficient_quota", "api key")

# How a Git platform says the token is no good.
_AUTH_FAILURE_TEXT = ("401", "403", "bad credentials", "unauthorized", "forbidden")


def could_not_evaluate(event: StandardRunFinished) -> bool:
    """The run could not be evaluated at all: the job itself failed, or every
    standard in it errored. This outranks failing standards."""
    all_errored = event.errored > 0 and event.passed == 0 and event.failed == 0
    return bool(event.error) or all_errored


def looks_like_auth_failure(error: str) -> bool:
    """The run's error reads like the Git platform refused the token. Only a
    hint: the policy confirms it with the platform before saying the
    connection is broken."""
    text = (error or "").lower()
    return any(marker in text for marker in _AUTH_FAILURE_TEXT)


def standards_failing(event: StandardRunFinished) -> bool:
    """The run could be evaluated and left standards failing."""
    return event.failed > 0 and not could_not_evaluate(event)


def turned_critical(score_before, score_after) -> bool:
    """The project's score crossed into critical with this run. A project
    that was already critical, or had no score yet, did not "drop"."""
    before = level_from_score(score_before)
    return before not in (CRITICAL, UNKNOWN) and level_from_score(score_after) == CRITICAL


def ai_provider_refused(event: DependencyInferenceFailed) -> bool:
    """The map failed because the AI provider refused GitGrit: a bad key, no
    credit, or no access to the model. That is the workspace's AI setup, not
    this one map."""
    if event.provider_status in _PROVIDER_REFUSALS:
        return True
    error = (event.error or "").lower()
    return any(text in error for text in _PROVIDER_REFUSAL_TEXT)


def graph_broke(event: DependencyInferenceFailed) -> bool:
    """A dependency map that used to build failed for a reason other than the
    AI provider. A map that never built (no AI model, say) would fail on
    every push, so it is not worth telling."""
    return event.had_worked_before and not ai_provider_refused(event)
