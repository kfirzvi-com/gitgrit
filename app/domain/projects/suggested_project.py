"""An app, service or library found inside a repository, offered as a
project of its own.

The dependency analysis of a whole-repository project lists the
independently built or deployed units it finds (a monorepo's apps/,
services/, packages/). Each is suggested on the project page until a project
is added at its path.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from app.domain.projects.project_kind import ProjectKind
from app.domain.projects.root_path import InvalidRootPath, RootPath

MAX_SUGGESTIONS = 25
MAX_TECHNOLOGIES = 20


@dataclass(frozen=True)
class SuggestedProject:
    path: str
    name: str
    kind: str = ProjectKind.OTHER.value
    description: str = ""
    technologies: tuple[str, ...] = ()
    # Stacks the unit was in before it was a project (carried over by
    # migration 0061 from the diagram's earlier model); it joins them when added.
    stack_ids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> SuggestedProject:
        return cls(
            path=data.get("path", ""),
            name=data.get("name", ""),
            kind=ProjectKind.parse(data.get("kind")).value,
            description=data.get("description", ""),
            technologies=tuple(data.get("technologies", ())),
            stack_ids=tuple(str(s) for s in data.get("stack_ids", ())),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["technologies"] = list(self.technologies)
        data["stack_ids"] = list(self.stack_ids)
        return data

    @staticmethod
    def still_open(suggestions: Iterable[SuggestedProject], added_paths: Iterable[str]) -> list[SuggestedProject]:
        """The suggestions no project has been added at yet."""
        added = set(added_paths)
        return [s for s in suggestions if s.path not in added]

    @classmethod
    def from_discovery(
        cls, found: Iterable[SuggestedProject], tree: Iterable[str], *, limit: int = MAX_SUGGESTIONS
    ) -> tuple[SuggestedProject, ...]:
        """The units a discovery found that are worth suggesting.

        * paths are normalised; one that leaves the repository, or has no
          file under it, is dropped (the model named a directory that does
          not exist), and so is the repository root (that is the project
          itself);
        * duplicates by path collapse to the first;
        * a missing name falls back to the last path segment, an unknown
          kind becomes ``other``;
        * a repository with a single unit is that unit: nothing to suggest;
        * at most ``limit``, sorted by path.
        """
        dirs: set[str] = set()
        for f in tree:
            parts = f.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))

        out: list[SuggestedProject] = []
        seen: set[str] = set()
        saw_root = False
        for s in found:
            try:
                path = RootPath.parse(s.path).value
            except InvalidRootPath:
                continue
            if not path:
                saw_root = True
                continue
            if path not in dirs or path in seen:
                continue
            seen.add(path)
            out.append(
                SuggestedProject(
                    path=path,
                    name=((s.name or "").strip() or path.rsplit("/", 1)[-1])[:255],
                    kind=ProjectKind.parse(s.kind).value,
                    description=(s.description or "")[:2000],
                    technologies=_clean_technologies(s.technologies),
                )
            )
            if len(out) >= limit:
                break
        if len(out) == 1 and not saw_root:
            return ()
        return tuple(sorted(out, key=lambda s: s.path))


def _clean_technologies(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for t in values or ():
        t = (t or "").strip()[:60]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return tuple(out[:MAX_TECHNOLOGIES])
