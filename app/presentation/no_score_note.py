from __future__ import annotations

from app.domain.scoring import CommitScoreOutcome

# What a commit with no score and no reason on record is missing.
NO_RESULT = "not every standard has a result"


class NoScoreNote:
    """Why a commit, and so its branch and project, shows no grade: it is
    still being checked, or it has no score (a standard errored or never
    ran in its newest run). One wording for the project cards, the
    health-count lists, the map and the Overview and Results tabs."""

    @staticmethod
    def text(subject) -> str:
        """``subject``: a ``scoring.CheckRunRecord`` (a commit's run, checking
        included) or a CommitScore. Empty for a verdict (an F or a number)."""
        if subject is None or subject.outcome is None:
            return ""
        sha = subject.commit_sha[:7] if hasattr(subject, "commit_sha") else subject.sha[:7]
        if subject.outcome is CommitScoreOutcome.CHECKING:
            standing = subject.standing
            return f"Checking commit {sha}: {standing.finished_count} of {standing.expected_count} standards done…"
        if subject.outcome is CommitScoreOutcome.NO_SCORE:
            reason = (subject.standing.reason if hasattr(subject, "standing") else subject.reason) or NO_RESULT
            return f"No score on commit {sha}: {reason}."
        return ""
