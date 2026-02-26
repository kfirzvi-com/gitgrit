from __future__ import annotations

from abc import ABC, abstractmethod


class BaseProvider(ABC):
    @abstractmethod
    def list_files(self) -> list[str]: ...

    @abstractmethod
    def get_languages(self) -> dict[str, float]: ...

    @abstractmethod
    def get_members(self) -> list[dict]: ...

    @abstractmethod
    def get_contributors(self) -> list[dict]: ...

    @abstractmethod
    def get_default_branch(self) -> str: ...

    @abstractmethod
    def get_topics(self) -> list[str]: ...

    @abstractmethod
    def get_metadata(self) -> dict: ...
