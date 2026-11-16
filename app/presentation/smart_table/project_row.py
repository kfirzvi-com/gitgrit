from __future__ import annotations

from dataclasses import dataclass

from app.application import scoring
from app.application.project_health_counts import ProjectHealthCounts
from app.domain.health import counted_level
from app.domain.models import Project
from app.domain.score_representation import ScoreTone

# Between several values in one data-filter-/data-group- attribute.
SEPARATOR = "|"

# Health, worst first: the order a "worst first" sort and the health groups take.
HEALTH_ORDER = (ScoreTone.FAILED, ScoreTone.NEEDS_ATTENTION, ScoreTone.HEALTHY)


@dataclass
class ProjectRow:
    """A project as the Projects table shows it: its newest commit on the
    default branch (``head``, a ``CheckRunRecord``, ``None`` when never
    checked), the score it got, and the stacks its components are in.

    Its health is the count it goes in when projects are counted
    (``ProjectHealthCounts``): a project with no grade needs attention."""

    project: Project
    head: object = None
    stacks: tuple = ()

    @classmethod
    def for_projects(cls, projects) -> list["ProjectRow"]:
        """A row per project, every head read at once. ``projects`` should
        prefetch ``components__stacks``."""
        projects = list(projects)
        heads = scoring.project_heads(projects)
        return [cls(project=p, head=heads.get(p.pk), stacks=cls._stacks_of(p)) for p in projects]

    @staticmethod
    def _stacks_of(project) -> tuple:
        stacks = {s.pk: s for c in project.components.all() for s in c.stacks.all()}
        return tuple(sorted(stacks.values(), key=lambda s: s.name.lower()))

    @property
    def score(self):
        return self.head.score if self.head else None

    @property
    def score_value(self):
        return self.score.value if self.score else None

    @property
    def health(self) -> ScoreTone:
        return counted_level(ProjectHealthCounts.project_health(self.score))

    @property
    def health_value(self) -> str:
        """``health:`` as a query says it: ``needs-attention``."""
        return self.health_slug(self.health)

    @staticmethod
    def health_slug(tone) -> str:
        return ScoreTone(tone).value.replace("_", "-")

    @property
    def checked_at(self):
        return self.head.check.created_at if self.head else None

    # --- What the row sorts by (data-sort-*) --------------------------------

    @property
    def sort_score(self) -> str:
        """Its score; a failed project (a Required standard failed) below
        every score, a project with no grade empty (last either way)."""
        if self.score and self.score.failed:
            return "-1"
        return "" if self.score_value is None else str(self.score_value)

    @property
    def sort_health(self) -> int:
        """Worst first: failed, then needs attention, then healthy; lowest
        score first within each."""
        return HEALTH_ORDER.index(self.health) * 1000 + int(self.score_value or 0)

    @property
    def sort_lifecycle(self) -> int:
        return list(Project.Lifecycle.values).index(self.project.lifecycle)

    @property
    def sort_checked(self) -> str:
        return str(int(self.checked_at.timestamp())) if self.checked_at else ""

    # --- What the row is filtered and grouped by (data-filter-*, data-group-*) -

    @property
    def stack_names(self) -> str:
        return SEPARATOR.join(self._clean(s.name) for s in self.stacks)

    @property
    def stack_values(self) -> str:
        return self.stack_names.lower()

    @property
    def owner_value(self) -> str:
        return self._clean(self.project.owner)

    @property
    def language_values(self) -> str:
        return SEPARATOR.join(self._clean(str(lang)).lower() for lang in self.project.languages or ())

    @staticmethod
    def _clean(text: str) -> str:
        """A value fit for a ``|``-separated attribute."""
        return (text or "").replace(SEPARATOR, "/").strip()
