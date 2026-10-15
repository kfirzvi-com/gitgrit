"""Who runs GitGrit itself: the superusers. Pure Python (no Django).

Superusers approve access requests, create workspaces, open any workspace
(the support view) and manage each other. The rules:
- Only a superuser makes or unmakes a superuser.
- Only an active account can be made one.
- There is always at least one active superuser: the last one can't be
  revoked, deactivated or deleted, or nobody could run GitGrit.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.events import SuperuserGranted, SuperuserRevoked


class SuperuserRuleError(Exception):
    """A change the superuser rules don't allow. The message is for people."""


class NotAllowed(SuperuserRuleError):
    pass


class LastSuperuser(SuperuserRuleError):
    def __init__(self):
        super().__init__(
            "GitGrit needs at least one superuser. Make someone else a superuser first."
        )


@dataclass(frozen=True)
class Account:
    user_id: str
    is_active: bool = True
    is_superuser: bool = False


class Superusers:
    """The active superusers, as the rules see them."""

    def __init__(self, user_ids):
        self._ids = {str(u) for u in user_ids}

    def __contains__(self, user_id) -> bool:
        return str(user_id) in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    def can_revoke(self, actor_id, account: Account) -> bool:
        try:
            self._check_revoke(actor_id, account)
        except SuperuserRuleError:
            return False
        return True

    def grant(self, actor_id, account: Account) -> SuperuserGranted:
        self._require_superuser(actor_id)
        if account.is_superuser or account.user_id in self:
            raise SuperuserRuleError("Already a superuser.")
        if not account.is_active:
            raise NotAllowed(
                "Only active accounts can be superusers. Approve their access request first."
            )
        self._ids.add(str(account.user_id))
        return SuperuserGranted(user_id=str(account.user_id), granted_by_user_id=str(actor_id))

    def revoke(self, actor_id, account: Account) -> SuperuserRevoked:
        self._check_revoke(actor_id, account)
        self._ids.discard(str(account.user_id))
        return SuperuserRevoked(user_id=str(account.user_id), revoked_by_user_id=str(actor_id))

    def ensure_can_lose(self, user_id) -> None:
        """The invariant alone, for a superuser disappearing without anyone
        deciding it here: deactivated or deleted in the Django admin."""
        if str(user_id) in self and len(self) == 1:
            raise LastSuperuser()

    def _require_superuser(self, actor_id):
        if actor_id not in self:
            raise NotAllowed("Only superusers manage superusers.")

    def _check_revoke(self, actor_id, account: Account) -> None:
        self._require_superuser(actor_id)
        if account.user_id not in self:
            raise SuperuserRuleError("Not a superuser.")
        self.ensure_can_lose(account.user_id)
