"""Who is in a workspace, and as what. Pure Python (no Django).

The ``Roster`` is a workspace's members as the business rules see them. It
decides every change to them and answers each with the domain event that
records it; the application layer loads it, applies the event to storage and
publishes it.

The rules:
- A workspace always has at least one owner, so it is never empty either.
  Its last owner can't step down, be removed or leave; deleting the whole
  workspace is the only way out.
- Owners and admins manage members and admins.
- Only owners make someone an owner, or change or remove an owner.
- Members join by accepting an invitation; owners and admins send them
  (only owners invite an owner). The exceptions are a superuser's: approving
  an access request, and naming a new workspace's owner.
- Anyone may leave, except the last owner.
- Only owners delete the workspace.
- A superuser acts as an owner in every workspace (the support view).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.domain.events import MemberJoined, MemberRemoved, MemberRoleChanged

OWNER = "owner"
ADMIN = "admin"
MEMBER = "member"
ROLES = (OWNER, ADMIN, MEMBER)
ROLE_LABELS = {OWNER: "Owner", ADMIN: "Admin", MEMBER: "Member"}


class MembershipRuleError(Exception):
    """A change the workspace rules don't allow. The message is for people."""


class UnknownRole(MembershipRuleError):
    def __init__(self, role):
        super().__init__(f"Unknown role {role!r}.")


class NotAllowed(MembershipRuleError):
    pass


class LastOwner(MembershipRuleError):
    def __init__(self, workspace_name: str = ""):
        where = f'"{workspace_name}"' if workspace_name else "the workspace"
        super().__init__(
            f"That would leave {where} without an owner. Make someone else an owner first."
        )


class AlreadyMember(MembershipRuleError):
    def __init__(self):
        super().__init__("Already a member of this workspace.")


@dataclass(frozen=True)
class Seat:
    """One person's place in the workspace."""

    user_id: str
    role: str


@dataclass(frozen=True)
class Actor:
    """Whoever is asking: their own role here (None when they aren't a
    member) and whether they are a superuser."""

    user_id: str
    role: str | None = None
    is_superuser: bool = False

    @property
    def acting_role(self) -> str | None:
        return OWNER if self.is_superuser else self.role

    @property
    def manages_members(self) -> bool:
        return self.acting_role in (OWNER, ADMIN)

    @property
    def manages_owners(self) -> bool:
        return self.acting_role == OWNER


class Roster:
    def __init__(self, workspace_id: str, seats, workspace_name: str = ""):
        self.workspace_id = str(workspace_id)
        self.workspace_name = workspace_name
        self._seats = {str(s.user_id): s for s in seats}

    # --- Reading ----------------------------------------------------------

    def seat_of(self, user_id) -> Seat | None:
        return self._seats.get(str(user_id))

    def actor(self, user_id, *, is_superuser: bool = False) -> Actor:
        seat = self.seat_of(user_id)
        return Actor(
            user_id=str(user_id),
            role=seat.role if seat else None,
            is_superuser=is_superuser,
        )

    @property
    def owner_count(self) -> int:
        return sum(s.role == OWNER for s in self._seats.values())

    def is_last_owner(self, user_id) -> bool:
        seat = self.seat_of(user_id)
        return seat is not None and seat.role == OWNER and self.owner_count == 1

    def assignable_roles(self, actor: Actor, user_id=None) -> tuple[str, ...]:
        """The roles ``actor`` may give ``user_id`` (or a newcomer, when
        None). Empty when they may not change that person at all."""
        if not actor.manages_members:
            return ()
        seat = self.seat_of(user_id) if user_id is not None else None
        if seat is not None:
            if seat.role == OWNER and not actor.manages_owners:
                return ()
            if self.is_last_owner(seat.user_id):
                return ()
        return tuple(r for r in ROLES if r != OWNER or actor.manages_owners)

    def can_remove(self, actor: Actor, user_id) -> bool:
        try:
            self._check_removal(actor, self._require(user_id))
        except MembershipRuleError:
            return False
        return True

    def can_delete_workspace(self, actor: Actor) -> bool:
        """Deleting the workspace is the owners' call (and a superuser's)."""
        return actor.manages_owners

    # --- Deciding ---------------------------------------------------------

    def add(self, actor: Actor, user_id, role: str) -> MemberJoined:
        self._check_role(role)
        if self.seat_of(user_id) is not None:
            raise AlreadyMember()
        if role not in self.assignable_roles(actor):
            raise self._why_not(actor, role)
        self._seats[str(user_id)] = Seat(str(user_id), role)
        return MemberJoined(
            tenant_id=self.workspace_id,
            user_id=str(user_id),
            role=role,
            added_by_user_id=actor.user_id,
        )

    # --- Invitations ------------------------------------------------------
    # Nobody is added by someone else: a member invites, the person accepts
    # (app.domain.models.WorkspaceInvitation). The roster decides who may
    # invite whom, and admits whoever accepts.

    def check_invite(self, actor: Actor, role: str) -> None:
        """``actor`` may invite someone in as ``role``, or this raises."""
        self._check_role(role)
        if role not in self.assignable_roles(actor):
            raise self._why_not(actor, role)

    def can_manage_invitation(self, actor: Actor, role: str) -> bool:
        """Resend or revoke an invitation for ``role``: the same people who
        could have sent it."""
        return role in self.assignable_roles(actor)

    def admit(self, user_id, role: str, invited_by_user_id=None) -> MemberJoined:
        """Someone accepted an invitation. Whoever invited them had the right
        to when they did; the invitation carries it."""
        self._check_role(role)
        if self.seat_of(user_id) is not None:
            raise AlreadyMember()
        self._seats[str(user_id)] = Seat(str(user_id), role)
        return MemberJoined(
            tenant_id=self.workspace_id,
            user_id=str(user_id),
            role=role,
            added_by_user_id=str(invited_by_user_id) if invited_by_user_id else None,
        )

    def change_role(self, actor: Actor, user_id, new_role: str) -> MemberRoleChanged | None:
        """None when the role is already ``new_role``: nothing to record."""
        self._check_role(new_role)
        seat = self._require(user_id)
        if seat.role == new_role:
            return None
        if not actor.manages_members:
            raise NotAllowed("Only owners and admins change roles.")
        if OWNER in (seat.role, new_role) and not actor.manages_owners:
            raise NotAllowed("Only owners make or unmake owners.")
        if self.is_last_owner(seat.user_id):
            raise LastOwner(self.workspace_name)
        self._seats[seat.user_id] = replace(seat, role=new_role)
        return MemberRoleChanged(
            tenant_id=self.workspace_id,
            user_id=seat.user_id,
            old_role=seat.role,
            new_role=new_role,
            changed_by_user_id=actor.user_id,
        )

    def remove(self, actor: Actor, user_id) -> MemberRemoved:
        """Remove ``user_id``; when that is ``actor`` themselves, they leave."""
        seat = self._require(user_id)
        self._check_removal(actor, seat)
        del self._seats[seat.user_id]
        return MemberRemoved(
            tenant_id=self.workspace_id,
            user_id=seat.user_id,
            removed_by_user_id=actor.user_id,
        )

    def ensure_can_lose(self, user_id) -> None:
        """The invariant alone, for a seat disappearing without anyone's
        say-so (the person's account being deleted, say)."""
        if self.is_last_owner(user_id):
            raise LastOwner(self.workspace_name)

    # --- Internals --------------------------------------------------------

    def _require(self, user_id) -> Seat:
        seat = self.seat_of(user_id)
        if seat is None:
            raise MembershipRuleError("Not a member of this workspace.")
        return seat

    @staticmethod
    def _check_role(role):
        if role not in ROLES:
            raise UnknownRole(role)

    def _check_removal(self, actor: Actor, seat: Seat) -> None:
        leaving = seat.user_id == actor.user_id
        if not leaving:
            if not actor.manages_members:
                raise NotAllowed("Only owners and admins remove members.")
            if seat.role == OWNER and not actor.manages_owners:
                raise NotAllowed("Only owners remove owners.")
        if self.is_last_owner(seat.user_id):
            raise LastOwner(self.workspace_name)

    @staticmethod
    def _why_not(actor: Actor, role: str) -> NotAllowed:
        if not actor.manages_members:
            return NotAllowed("Only owners and admins add members.")
        return NotAllowed(f"Only owners make someone {ROLE_LABELS[role].lower()}.")


def found(workspace_id, founder_user_id, *, role: str = OWNER, by_user_id=None, workspace_name=""):
    """A new workspace's roster: its first person, who is its owner. Returns
    the roster and the event that records them joining."""
    if role != OWNER:
        raise NotAllowed("The first person in a new workspace is its owner.")
    roster = Roster(workspace_id, [], workspace_name)
    roster._seats[str(founder_user_id)] = Seat(str(founder_user_id), OWNER)
    event = MemberJoined(
        tenant_id=roster.workspace_id,
        user_id=str(founder_user_id),
        role=OWNER,
        added_by_user_id=str(by_user_id) if by_user_id is not None else None,
    )
    return roster, event
