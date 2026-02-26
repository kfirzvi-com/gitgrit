from __future__ import annotations

from providers.base import BaseProvider


class ProjectContext:
    def __init__(self, provider: BaseProvider) -> None:
        self._provider = provider

    def list_files(self) -> list[str]:
        return self._provider.list_files()

    def get_languages(self) -> dict[str, float]:
        return self._provider.get_languages()

    def get_members(self) -> list[dict]:
        return self._provider.get_members()

    def get_contributors(self) -> list[dict]:
        return self._provider.get_contributors()

    def get_default_branch(self) -> str:
        return self._provider.get_default_branch()

    def get_topics(self) -> list[str]:
        return self._provider.get_topics()

    def get_metadata(self) -> dict:
        return self._provider.get_metadata()
