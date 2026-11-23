"""Which repository paths a webhook event changed, so a push to a monorepo
runs only the projects whose directories it touched."""
from __future__ import annotations

import logging

from app.domain.events import DomainEvent
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger(__name__)


class ChangedPaths:
    """The paths an event changed, read from its payload when that lists them
    completely, else asked of the platform's compare API (once per event).
    ``None`` means unknown, which every project covers: running a project
    needlessly beats missing a change."""

    def __init__(self, event: DomainEvent):
        self._event = event
        self._resolved = False
        self._paths: tuple[str, ...] | None = event.changed_paths

    def projects_touched(self, projects) -> list:
        """The ``projects`` (all on the event's repository) the event concerns.
        Whole-repository projects always are; the compare API is only asked
        when some project sits inside the repository."""
        projects = list(projects)
        if all(not p.root_path for p in projects):
            return projects
        paths = self.paths(projects[0])
        touched = [p for p in projects if p.covers(paths)]
        skipped = [p.name for p in projects if p not in touched]
        if skipped:
            logger.info("Event changed nothing under %s; not running them", ", ".join(skipped))
        return touched

    def paths(self, project) -> tuple[str, ...] | None:
        if self._paths is None and not self._resolved:
            self._resolved = True
            self._paths = self._compare(project)
        return self._paths

    def _compare(self, project) -> tuple[str, ...] | None:
        base, head = self._event.base_sha, self._event.commit_sha
        if not base or not head or self._event.event_type not in ("push", "pull_request"):
            return None
        try:
            files = get_platform_client(project.platform_connection).changed_files(
                project.external_id, project.full_path, base, head
            )
        except Exception:
            logger.exception("Couldn't compare %s...%s on %s", base, head, project.full_path)
            return None
        return tuple(files) if files is not None else None
