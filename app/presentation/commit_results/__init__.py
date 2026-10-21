"""How a commit's standard runs are laid out on the project page's Results
tab: ``CommitResultGrouping`` puts them in ``CommitResultGroup``s."""
from app.presentation.commit_results.commit_result_group import CommitResultGroup
from app.presentation.commit_results.commit_result_grouping import CommitResultGrouping

__all__ = ["CommitResultGroup", "CommitResultGrouping"]
