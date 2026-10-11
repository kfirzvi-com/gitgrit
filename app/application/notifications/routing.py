"""Routing policy: the one place that decides who hears each kind of
notification, and on which channels.

A ``Route`` is an audience plus channels. An audience is a list of
specifications (``Admins``, ``Team``, ``Triggerer``), each of which finds its
users for a given notification; the route's recipients are their union.
Everyone is filtered through membership of the notification's workspace, so a
notification never reaches anyone outside it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.models import Membership, Notification
from app.domain.notifications import Kind

logger = logging.getLogger(__name__)


class Admins:
    """The workspace's owners and admins."""

    def user_ids(self, notification: Notification) -> set[str]:
        return _members(notification, roles=("owner", "admin"))


class Team:
    """Everyone in the workspace."""

    def user_ids(self, notification: Notification) -> set[str]:
        return _members(notification, roles=("owner", "admin", "member"))


class Triggerer:
    """Whoever started the run behind the notification, if they are a member."""

    def user_ids(self, notification: Notification) -> set[str]:
        named = notification.triggered_by_user_ids
        if not named:
            return set()
        return _members(notification, user_ids=named)


@dataclass(frozen=True)
class Route:
    audience: tuple
    channels: tuple[str, ...]

    def recipients(self, notification: Notification) -> list[str]:
        """Distinct user ids, in a stable order."""
        ids = set()
        for spec in self.audience:
            ids |= spec.user_ids(notification)
        return sorted(ids)


ROUTES: dict[str, Route] = {
    Kind.RUN_FAILED: Route((Admins(), Triggerer()), ("inbox",)),
    Kind.STANDARDS_FAILING: Route((Admins(), Triggerer()), ("inbox",)),
    Kind.GRAPH_FAILED: Route((Admins(), Triggerer()), ("inbox",)),
}

# An unknown kind (most likely a typo) still lands somewhere visible.
FALLBACK = Route((Admins(),), ("inbox",))


def route_for(kind: str) -> Route:
    route = ROUTES.get(kind)
    if route is None:
        logger.warning("No notification route for kind %r; using the fallback", kind)
        return FALLBACK
    return route


def _members(notification, roles=None, user_ids=None) -> set[str]:
    members = Membership.objects.filter(tenant_id=notification.tenant_id)
    if roles is not None:
        members = members.filter(role__in=roles)
    if user_ids is not None:
        members = members.filter(user_id__in=user_ids)
    return {str(u) for u in members.values_list("user_id", flat=True)}
