from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BudgetableModel:
    """A model a workspace can give a budget: its provider, the roles that
    use it (GitGrit calls those), and whether it has a budget yet. Budgets
    are an allow-list, so a model without one does not run."""

    provider_id: str
    provider_name: str
    model: str
    roles: tuple = field(default_factory=tuple)  # role labels, e.g. ("Reasoning",)
    has_budget: bool = False

    @property
    def blocked(self) -> bool:
        return not self.has_budget
