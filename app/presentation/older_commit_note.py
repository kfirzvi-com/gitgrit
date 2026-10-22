from __future__ import annotations

# What a commit with no score and no reason on record is missing.
NO_RESULT = "not every standard has a result"


class OlderCommitNote:
    """The sentence that says a project shows an older commit than its
    newest, because the newest has no score (a standard errored or never
    ran; ``scoring.newest_without_score``). One wording for the project
    cards, the health-count lists and the map."""

    @staticmethod
    def text(newest, shown=None) -> str:
        """``newest``: the newest commit's CommitScore (no score); ``shown``:
        the CommitScore shown instead, or None when there is none."""
        reason = newest.reason or NO_RESULT
        if shown is None:
            return f"No score: the newest commit, {newest.commit_sha[:7]}, has none ({reason})."
        return (
            f"Not the latest commit: showing {shown.commit_sha[:7]}. "
            f"The newest, {newest.commit_sha[:7]}, has no score ({reason})."
        )
