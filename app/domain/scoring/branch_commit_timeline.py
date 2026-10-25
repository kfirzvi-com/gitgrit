from __future__ import annotations

from datetime import datetime


class BranchCommitTimeline:
    """How a branch's commits and their scores are ordered. A branch reads
    its newest commit, whatever its outcome (checking, no score, failed or
    scored), never merely the newest run's: checking an old commit again
    must not replace a newer commit's. And a commit reads its newest
    check."""

    @staticmethod
    def commit_ordered_at(committed_at: datetime | None, first_checked_at: datetime) -> datetime:
        """When a commit counts as made: its commit time, else when it was
        first checked."""
        return committed_at or first_checked_at

    @classmethod
    def newest_checked_commit(cls, commit_checks):
        """The newest commit among a branch's commit checks (rows with
        ``commit_sha``, ``committed_at`` and ``created_at``), as its newest
        check: the one the branch reads. None without any."""
        with_commit = [c for c in commit_checks if c.commit_sha]
        if not with_commit:
            return None
        return max(
            with_commit, key=lambda c: (cls.commit_ordered_at(c.committed_at, c.created_at), c.created_at)
        )

    @staticmethod
    def last_score_per_commit(commit_scores_newest_first) -> dict:
        """Each commit's score (sha -> score row): its newest check's, the
        newest row, since every check saves one when it ends."""
        latest = {}
        for row in commit_scores_newest_first:
            latest.setdefault(row.commit_sha, row)
        return latest

    @staticmethod
    def branch_a_commit_is_read_on(
        score_branch: str | None, checked_branches_newest_first, default_branch: str
    ) -> str:
        """The branch of the commit's score, else the branch it was last
        checked on, else the project's default branch."""
        if score_branch:
            return score_branch
        return next(iter(checked_branches_newest_first), default_branch)
