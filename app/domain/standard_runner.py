from __future__ import annotations

from abc import ABC, abstractmethod


class StandardRunner(ABC):
    @abstractmethod
    def run(
        self, standard_code: str, input_config: dict, project_dir: str | None = None
    ) -> dict:
        """Execute a standard script and return the result dict. ``project_dir``
        is a directory of project files to read instead of a Git platform
        (an upload project's version)."""
        ...
