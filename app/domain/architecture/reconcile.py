"""Re-running inference must not lose what users did by hand.

Components are identified by *path*, so a component whose path is unchanged
keeps its identity (and its stack memberships) across runs. When the shape of
a repository changes — one root component becomes eight, or a service
disappears — the memberships of the components that vanish flow to the ones
that appear: "this repo is in Storefront" was said about the repository, so
it applies to whatever the repository turns out to contain.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable, Mapping


@dataclass(frozen=True)
class ReconcilePlan:
    keep: tuple[str, ...]
    create: tuple[str, ...]
    remove: tuple[str, ...]

    @property
    def shape_changed(self) -> bool:
        return bool(self.create and self.remove)


def plan_components(existing_paths: Iterable[str], discovered_paths: Iterable[str]) -> ReconcilePlan:
    """Which paths to keep, create and remove. Order follows ``discovered_paths``
    for keep/create and ``existing_paths`` for remove."""
    existing = list(dict.fromkeys(existing_paths))
    discovered = list(dict.fromkeys(discovered_paths))
    existing_set = set(existing)
    discovered_set = set(discovered)
    return ReconcilePlan(
        keep=tuple(p for p in discovered if p in existing_set),
        create=tuple(p for p in discovered if p not in existing_set),
        remove=tuple(p for p in existing if p not in discovered_set),
    )


def inherited_memberships(
    plan: ReconcilePlan, memberships: Mapping[str, Iterable[Hashable]]
) -> dict[str, set[Hashable]]:
    """Stack memberships the *created* components inherit: the union of the
    *removed* components' stacks. Empty unless the shape actually changed
    (something removed and something created), so a plain re-run that adds a
    component to an otherwise stable repository does not spread memberships."""
    if not plan.shape_changed:
        return {}
    inherited: set[Hashable] = set()
    for path in plan.remove:
        inherited.update(memberships.get(path, ()))
    if not inherited:
        return {}
    return {path: set(inherited) for path in plan.create}
