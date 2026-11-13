from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BudgetableModel:
    """A model a workspace can give a budget: its provider, the roles that
    use it (so GitGrit calls it), and whether it has a budget yet."""

    provider_id: str
    provider_name: str
    model: str
    roles: tuple = field(default_factory=tuple)  # role labels, e.g. ("Reasoning",)
    has_budget: bool = False

    @property
    def blocked(self) -> bool:
        """Budgets are an allow-list (``ModelAccess``): a model with no
        budget does not run at all."""
        return not self.has_budget
