from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckPlan:
    """Which standards a check runs and which it carries: takes the newest
    finished result of from earlier runs on its branch instead of running
    them (``app.domain.schedules``, rule 5). The check expects both, so its
    commit is scored from every standard, whatever ran it.

    Standard ids, in order."""

    run: tuple[str, ...]
    carried: tuple[str, ...] = ()

    @property
    def expected(self) -> tuple[str, ...]:
        return self.run + self.carried

    @classmethod
    def for_change(cls, matching, on_default_branch: bool) -> CheckPlan:
        """A push or pull request: it runs the ``matching`` standards
        (``AttachedStandard``s whose criteria match the event) except those
        that run only on a schedule. On the default branch those are carried,
        so the project score keeps them; on any other branch they are not
        part of the check: a change is checked by what runs on changes."""
        run = tuple(str(s.standard_id) for s in matching if not s.scheduled_only)
        carried = tuple(str(s.standard_id) for s in matching if s.scheduled_only) if on_default_branch else ()
        return cls(run, carried)

    @classmethod
    def for_schedule(cls, due, current, applying) -> CheckPlan:
        """A scheduled run on the default branch: it runs the ``due``
        standards and carries the rest of what the branch's score is made of:
        the standards its ``current`` (newest) check expected that still
        apply (``applying``), so the score the run gives is that score with
        the due standards' results refreshed. Without a current check it
        expects the due standards alone."""
        run = tuple(dict.fromkeys(str(i) for i in due))
        still = {str(i) for i in applying}
        carried = tuple(str(i) for i in dict.fromkeys(current) if str(i) in still and str(i) not in run)
        return cls(run, carried)
