"""Pure grade rules: the letter a project earns from its standards' own
verdicts, and the gate a critical standard puts in front of it. No I/O, no ORM.

A ``Result`` is the latest counting outcome of one attachment on the
standard's home branch (the project's default branch, unless the standard's
Branch/Tag Filter names one branch literally); ``app.application.grading_service``
gathers them from the execution rows and everything here decides over the
values.
Pass and fail are the standard's own verdict (the ``passed`` its script
returned, stored as the execution status); a standard's 0-100 score stays
visible per row but no longer aggregates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# Execution statuses as stored on ``StandardExecution.status``.
RUNNING = "running"
PASSED = "passed"
FAILED = "failed"
ERROR = "error"
SKIPPED = "skipped"

# ``StandardExecution.error_origin``: whose failure an ERROR row is.
STANDARD_ORIGIN = "standard"
PLATFORM_ORIGIN = "platform"

# Letters, best to worst. ``NO_GRADE`` is what a project with nothing
# evaluated shows, the same "—" as today's "no score".
A_PLUS = "A+"
A = "A"
B = "B"
C = "C"
D = "D"
F = "F"
NO_GRADE = "—"

# Pass-rate bands (percent, inclusive lower bound), checked top down; a rate
# below the last band is a D. The one place the thresholds live.
PASS_RATE_BANDS: tuple[tuple[int, str], ...] = (
    (100, A_PLUS),
    (90, A),
    (75, B),
    (60, C),
)

REASON_PERFECT = "perfect"
REASON_NO_RESULTS = "no results yet"

# Neglect caps: a standard left failing on its home branch for strictly
# more than this many days caps the letter, checked top down (worst first).
# The one place the day thresholds live.
NEGLECT_CAPS: tuple[tuple[int, str], ...] = (
    (30, C),
    (14, B),
)

# Letters worst to best, for worst-of roll-ups (workspace, stack).
LETTER_ORDER: tuple[str, ...] = (F, D, C, B, A, A_PLUS)

# Tones: the colour band a letter sits in, the one place the mapping lives.
# Health levels (``app.domain.health``), the badge and the dashboard
# all read it. ``unknown`` is no grade.
TONE_GOOD = "good"
TONE_ATTENTION = "attention"
TONE_FAILING = "failing"
TONE_UNKNOWN = "unknown"

_TONE_BY_LETTER = {
    A_PLUS: TONE_GOOD,
    A: TONE_GOOD,
    B: TONE_GOOD,
    C: TONE_ATTENTION,
    D: TONE_ATTENTION,
    F: TONE_FAILING,
}


def tone_for(letter: str | None) -> str:
    """The tone of a letter: F is failing, D and C need attention, A+, A
    and B are good; anything else (no grade) is unknown."""
    return _TONE_BY_LETTER.get(letter, TONE_UNKNOWN)


def worst_letter(letters) -> str:
    """The worst letter among those given, ignoring ungraded ones (so a
    project with nothing evaluated never drags a workspace or stack down).
    ``NO_GRADE`` when none is graded."""
    rank = {letter: i for i, letter in enumerate(LETTER_ORDER)}
    graded = [l for l in letters if l in rank]
    if not graded:
        return NO_GRADE
    return min(graded, key=rank.__getitem__)


@dataclass(frozen=True)
class Result:
    """The latest finished outcome of one attachment on its home branch.

    ``name`` is the standard's name, so a reason can say which critical
    standard is failing.
    ``first_failed_at`` lets the neglect cap count days without the database.
    """

    status: str
    critical: bool = False
    error_origin: str = STANDARD_ORIGIN
    name: str = ""
    # The attachment's neglect clock: when this standard first failed on its
    # home branch and has not passed since (``None`` when it is not failing,
    # or has no clock, as a commit's rows have).
    first_failed_at: datetime | None = None

    @property
    def counts(self) -> bool:
        """Finished, not skipped, and not GitGrit's own failure."""
        return self.status in (PASSED, FAILED, ERROR) and not self.platform_error

    @property
    def passed(self) -> bool:
        return self.status == PASSED

    @property
    def platform_error(self) -> bool:
        return self.status == ERROR and self.error_origin == PLATFORM_ORIGIN

    @property
    def unverified(self) -> bool:
        """Errored inside the standard's own run."""
        return self.status == ERROR and self.error_origin != PLATFORM_ORIGIN


@dataclass(frozen=True)
class Grade:
    letter: str
    reason: str

    @property
    def graded(self) -> bool:
        return self.letter != NO_GRADE


def branch_refs(branch: str, default_branch: str) -> tuple[str, ...]:
    """The spellings of ``branch`` an execution's ``ref`` may carry: bare
    (manual runs on a Branch/Tag Filter's literal branch), with the webhook's
    ``refs/heads/`` prefix, and empty when the branch is the project's
    default (a manual run with no filter reads the default branch)."""
    refs = (branch, f"refs/heads/{branch}")
    return refs + ("",) if branch == default_branch else refs


def is_home_branch_run(ref: str, home_branch: str, default_branch: str) -> bool:
    """Did this run read the standard's home branch? Runs on any other branch
    (a feature-branch push, a pull request) never count: a half-finished
    branch must not fail the project and a fix that only exists on a branch
    must not pass it before it merges."""
    return ref in branch_refs(home_branch, default_branch)


def counts_toward_grade(execution, home_branch: str, default_branch: str | None = None) -> bool:
    """Is this execution a home-branch run that finished without a platform
    error? Running and skipped rows never count. ``default_branch`` is the
    project's (the home branch itself when not given)."""
    if execution.status in (RUNNING, SKIPPED):
        return False
    if execution.status == ERROR and execution.error_origin == PLATFORM_ORIGIN:
        return False
    if default_branch is None:
        default_branch = home_branch
    return is_home_branch_run(execution.ref, home_branch, default_branch)


def letter_from_pass_rate(passed: int, total: int) -> str:
    """The A+…D band of ``passed`` out of ``total`` results."""
    if total <= 0:
        raise ValueError("a pass rate needs at least one result")
    rate = passed * 100 / total
    for floor, letter in PASS_RATE_BANDS:
        if rate >= floor:
            return letter
    return D


def is_gated(results) -> bool:
    """Does any critical result fail, or error inside its own run?"""
    return any(
        r.critical and r.counts and not r.passed for r in results
    )


def _names(results) -> str:
    return ", ".join(r.name or "a critical standard" for r in results)


def reason_for(results, letter: str, cap: str | None = None) -> str:
    """Why the grade is not one higher, in this priority: a critical result
    failing or unverified, then a neglect cap (``cap`` is its sentence, Bet
    2), then how many standards are failing, then "perfect"."""
    counting = [r for r in results if r.counts]
    gated = [r for r in counting if r.critical and not r.passed]
    if gated:
        parts = []
        failing = [r for r in gated if not r.unverified]
        unverified = [r for r in gated if r.unverified]
        if failing:
            parts.append(f"{_names(failing)} failing")
        if unverified:
            parts.append(f"could not verify {_names(unverified)}")
        return "; ".join(parts)
    if cap:
        return cap
    if not counting:
        return REASON_NO_RESULTS
    failing_count = sum(1 for r in counting if not r.critical and not r.passed)
    if failing_count:
        return f"{failing_count} standard{'' if failing_count == 1 else 's'} failing"
    return REASON_PERFECT


def neglect_cap(days_failing: int) -> str | None:
    """The letter a standard failing for ``days_failing`` days caps the grade
    at: B after more than 14 days, C after more than 30. ``None`` below."""
    for floor, letter in NEGLECT_CAPS:
        if days_failing > floor:
            return letter
    return None


def days_failing(first_failed_at: datetime | None, now: datetime) -> int:
    """Whole days since the clock started; 0 without a clock."""
    if first_failed_at is None:
        return 0
    return max((now - first_failed_at).days, 0)


def _longest_failing(results, now: datetime):
    """The not-passed result whose clock has run longest, and its days;
    ``(None, 0)`` when no failing result has a clock."""
    longest, most = None, 0
    for r in results:
        if r.passed or r.first_failed_at is None:
            continue
        days = days_failing(r.first_failed_at, now)
        if longest is None or days > most:
            longest, most = r, days
    return longest, most


def _worse(letter: str, cap: str | None) -> str:
    """``letter`` lowered to ``cap`` when the cap is worse; never raised."""
    if cap is None:
        return letter
    return worst_letter([letter, cap])


def letter_for(results, now: datetime | None = None) -> Grade:
    """The project grade and its reason.

    Any critical result failed or errored (standard origin) is an F. Otherwise
    the letter is the pass rate of the non-critical results; with none of
    those, A+ when every critical result passed, else no grade. A neglect
    cap (a standard failing on its home branch for more than 14 or 30
    days, by its ``first_failed_at`` against ``now``) then lowers the letter
    to the cap, never raises it, and never applies behind the gate.
    """
    results = list(results)
    now = now or datetime.now(timezone.utc)
    counting = [r for r in results if r.counts]
    if is_gated(counting):
        return Grade(F, reason_for(counting, F))
    non_critical = [r for r in counting if not r.critical]
    if non_critical:
        letter = letter_from_pass_rate(
            sum(1 for r in non_critical if r.passed), len(non_critical)
        )
    elif counting:
        letter = A_PLUS
    else:
        letter = NO_GRADE
    neglected, days = _longest_failing(counting, now)
    cap = neglect_cap(days) if neglected else None
    capped = _worse(letter, cap)
    # The cap explains the grade only when it is what holds the letter down.
    cap_reason = (
        f"{neglected.name or 'a standard'} failing for {days} days"
        if cap and capped == cap
        else None
    )
    return Grade(capped, reason_for(counting, capped, cap=cap_reason))


def unverified_transition(previous: Result | None, current: Result) -> bool:
    """Should the could-not-verify alert go out: a critical result errored in
    its own run when its previous counting result was not errored, or there
    was none. A repeat error is silent; after a pass the next error notifies
    again."""
    if not (current.critical and current.unverified):
        return False
    return previous is None or not previous.unverified
