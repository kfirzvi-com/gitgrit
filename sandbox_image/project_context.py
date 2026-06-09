from typing import Annotated

from providers.base import BaseProvider


def tool(method):
    """Mark a ProjectContext method as an LLM tool.

    The marked method's docstring becomes the tool description and its type
    hints define the tool parameters, so the LLM tool set is derived from this
    one place (see ``llm.make_project_tools``) and can never drift out of sync.
    Marking is opt-in: only decorated methods are exposed to the model.
    """
    method.__llm_tool__ = True
    return method


class ProjectContext:
    def __init__(self, provider: BaseProvider) -> None:
        self._provider = provider

    @tool
    def get_file_content(
        self, path: Annotated[str, "Repository-relative file path."]
    ) -> str | None:
        """Read the full contents of a file. Returns null if the file does not exist."""
        return self._provider.get_file_content(path)

    @tool
    def list_files(self) -> list[str]:
        """List every file path in the repository."""
        return self._provider.list_files()

    @tool
    def get_languages(self) -> dict[str, float]:
        """Return detected languages and their percentages."""
        return self._provider.get_languages()

    @tool
    def get_metadata(self) -> dict:
        """Return repository metadata (name, description, default branch, topics, etc.)."""
        return self._provider.get_metadata()

    def get_members(self) -> list[dict]:
        return self._provider.get_members()

    def get_contributors(self) -> list[dict]:
        return self._provider.get_contributors()

    def get_default_branch(self) -> str:
        return self._provider.get_default_branch()

    def get_topics(self) -> list[str]:
        return self._provider.get_topics()

    def get_file_last_commit_date(self, path: str) -> str | None:
        return self._provider.get_file_last_commit_date(path)
