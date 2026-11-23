from __future__ import annotations


class BranchCommitTimeline:
    """How a branch's checks and their scores are ordered: by when each
    check ran (its ``created_at``, saved by the run itself, whatever
    triggered it). A branch reads its newest check, whatever its outcome
    (checking, no score, failed or scored)."""

    @staticmethod
    def newest_checked_commit(commit_checks):
        """The newest check among a branch's commit checks (rows with
        ``commit_sha`` and ``created_at``) that has a commit: the one the
        branch reads. None without any."""
        with_commit = [c for c in commit_checks if c.commit_sha]
        if not with_commit:
            return None
        return max(with_commit, key=lambda c: c.created_at)

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
