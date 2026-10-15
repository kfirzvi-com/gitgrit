"""Notification routing: the one place that decides who hears each kind of
notification, and on which channels.

A ``Route`` is an audience plus channels. An audience is a list of
specifications (``Admins``, ``Team``, ``Triggerer``, ``AffectedMember``),
each of which finds its users for a given notification; the route's
recipients are their union.
Everyone is filtered through membership of the notification's workspace, so a
notification never reaches anyone outside it, and the person who made the
change behind it is left out: nobody is told about their own action.
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


class AffectedMember:
    """The member a membership notification is about, while still a member."""

    def user_ids(self, notification: Notification) -> set[str]:
        member = notification.member_user_id
        if not member:
            return set()
        return _members(notification, user_ids=[member])


@dataclass(frozen=True)
class Route:
    audience: tuple
    channels: tuple[str, ...]

    def recipients(self, notification: Notification) -> list[str]:
        """Distinct user ids, in a stable order, without the actor."""
        ids = set()
        for spec in self.audience:
            ids |= spec.user_ids(notification)
        ids.discard(notification.actor_user_id)
        return sorted(ids)


# Problems with a run go to the admins and whoever started it; changes to the
# workspace go to the admins. A critical standard that could not be verified
# gates the project for everyone, so everyone hears it.
_RUN = Route((Admins(), Triggerer()), ("inbox",))
_WORKSPACE = Route((Admins(),), ("inbox",))
_TEAM = Route((Team(),), ("inbox",))

ROUTES: dict[str, Route] = {
    Kind.RUN_FAILED: _RUN,
    Kind.STANDARDS_FAILING: _RUN,
    Kind.PROJECT_CRITICAL: _RUN,
    Kind.GRADE_UNVERIFIED: _TEAM,
    Kind.RUN_TIMED_OUT: _RUN,
    Kind.CONNECTION_BROKEN: _RUN,
    Kind.GRAPH_FAILED: _RUN,
    Kind.AI_PROVIDER_FAILED: _WORKSPACE,
    Kind.PROJECT_ADDED: _WORKSPACE,
    Kind.PROJECT_REMOVED: _WORKSPACE,
    Kind.MEMBER_JOINED: _WORKSPACE,
    Kind.MEMBER_REMOVED: _WORKSPACE,
    Kind.MEMBER_ROLE_CHANGED: Route((Admins(), AffectedMember()), ("inbox",)),
    Kind.STANDARD_CHANGED: _WORKSPACE,
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
