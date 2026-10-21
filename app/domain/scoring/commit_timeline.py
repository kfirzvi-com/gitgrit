from __future__ import annotations

from datetime import datetime


class CommitTimeline:
    """How a branch's commits and scores are ordered. A branch shows its
    newest commit's score, never merely the newest run's: checking an old
    commit again must not replace a newer commit's score."""

    @staticmethod
    def ordered_at(committed_at: datetime | None, checked_at: datetime) -> datetime:
        """When a commit counts as made: its commit time, else when it was
        first checked."""
        return committed_at or checked_at

    @classmethod
    def newest(cls, checks):
        """The newest commit among a branch's checks (rows with
        ``commit_sha``, ``committed_at`` and ``created_at``), or None."""
        checked = [c for c in checks if c.commit_sha]
        if not checked:
            return None
        return max(checked, key=lambda c: (cls.ordered_at(c.committed_at, c.created_at), c.created_at))

    @staticmethod
    def last_score_per_commit(scores_newest_first) -> dict:
        """Each commit's score (sha -> score row): the last one it reached. A
        newer check replaces it only when it completes too, so a commit's
        newest score row is its score."""
        latest = {}
        for row in scores_newest_first:
            latest.setdefault(row.commit_sha, row)
        return latest

    @staticmethod
    def branch_of(score_branch: str | None, checked_branches_newest_first, default_branch: str) -> str:
        """The branch a commit is read on: the branch of its score, else the
        branch it was last checked on, else the project's default branch."""
        if score_branch:
            return score_branch
        return next(iter(checked_branches_newest_first), default_branch)
