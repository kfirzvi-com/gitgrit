from typing import Annotated

from providers.base import BaseProvider

# A line longer than this is broken up before it is shown to a model. A
# minified bundle is often one line of hundreds of KB, which would leave a
# model only its first few thousand characters (tool results are capped).
LINE_WIDTH = 200
# Break after these where possible, so the pieces stay readable code.
_BREAK_AFTER = ";,{}()"
# One read returns at most this many characters of lines, under the cap the
# LLM loop puts on any tool result, and says where to continue.
MAX_READ_CHARS = 5000


def break_long_lines(text: str, width: int = LINE_WIDTH) -> list[str]:
    """``text``'s lines, each at most ``width`` characters: a longer line is
    split after the last ``;``, ``,``, brace or parenthesis in its window
    (keeping each piece at least half the width), else at the width."""
    out: list[str] = []
    for line in text.split("\n"):
        while len(line) > width:
            window = line[:width]
            cut = max(window.rfind(c) for c in _BREAK_AFTER) + 1
            if cut < width // 2:
                cut = width
            out.append(line[:cut])
            line = line[cut:]
        out.append(line)
    return out


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
    def get_file_size(
        self, path: Annotated[str, "Repository-relative file path."]
    ) -> int | None:
        """Return a file's size in bytes, or null if it does not exist or the size is unknown."""
        return self._provider.get_file_size(path)

    @tool
    def read_file_lines(
        self,
        path: Annotated[str, "Repository-relative file path."],
        start: Annotated[int, "First line to return, counting from 1."] = 1,
        count: Annotated[int, "Most lines to return; fewer come back when they are long."] = 100,
    ) -> dict | None:
        """Read part of a file as numbered lines, with the file's total line count and the line to continue from (null at the end). Long lines (e.g. a minified bundle) are broken into short ones first, so page through any large file with this. Returns null if the file does not exist."""
        content = self._provider.get_file_content(path)
        if content is None:
            return None
        lines = break_long_lines(content)
        start = max(1, int(start))
        count = max(1, int(count))
        numbered, used = [], 0
        for number in range(start, min(start + count, len(lines) + 1)):
            entry = f"{number}: {lines[number - 1]}"
            if numbered and used + len(entry) > MAX_READ_CHARS:
                break
            numbered.append(entry)
            used += len(entry)
        next_start = start + len(numbered)
        return {
            "path": path,
            "total_lines": len(lines),
            "lines": numbered,
            "next_start": next_start if next_start <= len(lines) else None,
        }

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

    @tool
    def get_members(self) -> list[dict]:
        """List the repository's members. Each entry has 'username' and 'role'."""
        return self._provider.get_members()

    @tool
    def get_contributors(self) -> list[dict]:
        """List contributors. Each entry has 'username' and 'commits' (count)."""
        return self._provider.get_contributors()

    @tool
    def get_default_branch(self) -> str:
        """Return the name of the repository's default branch (e.g. 'main')."""
        return self._provider.get_default_branch()

    @tool
    def get_topics(self) -> list[str]:
        """Return the repository's topics / tags."""
        return self._provider.get_topics()

    @tool
    def get_file_last_commit_date(
        self, path: Annotated[str, "Repository-relative file path."]
    ) -> str | None:
        """Return the ISO 8601 date of the last commit that touched a file, or null if unknown."""
        return self._provider.get_file_last_commit_date(path)
