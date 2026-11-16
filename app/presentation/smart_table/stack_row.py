from __future__ import annotations

from dataclasses import dataclass

from app.application.project_health_counts import ProjectHealthCounts
from app.domain.models import Stack

# Between several values in one data-filter-/data-group- attribute.
SEPARATOR = "|"


@dataclass
class StackRow:
    """A stack as the Stacks table shows it: its projects (each once, however
    many of its components are in the stack), counted by health, and the
    owners of those projects. A stack never gets one grade of its own."""

    stack: Stack
    projects: tuple
    health: ProjectHealthCounts

    @classmethod
    def for_stacks(cls, stacks) -> list["StackRow"]:
        """A row per stack, every project's score read once. ``stacks``
        should prefetch ``components__project``."""
        stacks = list(stacks)
        health = ProjectHealthCounts.for_stacks(stacks)
        rows = []
        for stack in stacks:
            projects = {c.project_id: c.project for c in stack.components.all()}.values()
            rows.append(cls(
                stack=stack,
                projects=tuple(sorted(projects, key=lambda p: p.name.lower())),
                health=health[stack.pk],
            ))
        return rows

    @property
    def component_count(self) -> int:
        return len(self.stack.components.all())

    @property
    def owners(self) -> tuple[str, ...]:
        return tuple(sorted({p.owner.strip() for p in self.projects if p.owner.strip()}, key=str.lower))

    @property
    def healthy_share(self) -> str:
        """How many of its projects are healthy, as a share (0 to 100):
        what "Health" sorts by. Empty when it has no projects."""
        if not self.health.total:
            return ""
        return str(round(100 * self.health.healthy / self.health.total))

    @property
    def owner_values(self) -> str:
        return SEPARATOR.join(self._clean(o) for o in self.owners)

    @property
    def project_values(self) -> str:
        return SEPARATOR.join(self._clean(p.name).lower() for p in self.projects)

    @property
    def health_values(self) -> str:
        """What ``has:`` matches: the health of any of its projects."""
        present = []
        if self.health.failed:
            present.append("failed")
        if self.health.needs_attention:
            present.append("needs-attention")
        if self.health.healthy:
            present.append("healthy")
        return SEPARATOR.join(present)

    @staticmethod
    def _clean(text: str) -> str:
        return (text or "").replace(SEPARATOR, "/").strip()
