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
    def get_file_content(self, path: str) -> str | None: ...

    @abstractmethod
    def get_metadata(self) -> dict: ...

    @abstractmethod
    def get_file_last_commit_date(self, path: str) -> str | None:
        """Return the ISO 8601 timestamp of the most recent commit that touched
        ``path`` on the default branch, or None if the file does not exist or
        has no commit history. Used by standards that check file freshness."""
        ...

    def get_file_size(self, path: str) -> int | None:
        """Return a file's size in bytes, or None if it does not exist or the
        provider cannot tell. Lets standards check files they cannot read as
        text (images, audio, wasm). Override per provider."""
        return None
