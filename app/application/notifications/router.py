"""Routing policy: the one place that decides who hears what."""

import logging

from app.domain.notifications import Audience, Rule

logger = logging.getLogger(__name__)

RULES: dict[str, Rule] = {
    "run.failed": Rule(Audience.admins(), ("inbox",)),
    "standards.failing": Rule(Audience.admins(), ("inbox",)),
    "graph.failed": Rule(Audience.admins(), ("inbox",)),
}


def rule_for(kind: str) -> Rule:
    """Return the rule for a kind.

    An unknown kind (most likely a typo) falls back to admins on the inbox, so
    it still lands somewhere visible instead of vanishing.
    """
    rule = RULES.get(kind)
    if rule is None:
        logger.warning("No notification rule for kind %r; using the fallback", kind)
        return Rule(Audience.admins(), ("inbox",))
    return rule
