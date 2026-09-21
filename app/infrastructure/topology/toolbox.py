"""Read-only repository tools handed to the model.

Records what the model actually inspected (``tree_size``, ``files_read``) so
the caller can refuse to save an answer that was never grounded in the repo —
a model that reads nothing and guesses must not produce an ``ok`` map.

Every tool returns a string the model can act on. An empty list or empty
string is never returned for a miss: models that get silence retry the same
wrong argument until the round-trip cap and then invent a result.
"""
from __future__ import annotations

from typing import Annotated

from app.application.architecture.ports import RepositorySnapshot
from app.domain.architecture.topology import clean_path
from app.infrastructure.llm_agent import tool

# Directories that are never dependency evidence and routinely dwarf the rest
# of the tree (committed node_modules, build output). Hidden from listings so
# the real manifests fit inside the tool-result cap; read_file can still open
# anything inside them.
NOISE_DIRS = frozenset({
    "node_modules", "vendor", "dist", "build", "target", "__pycache__",
    ".git", ".terraform", ".venv", "venv", ".idea", ".vscode",
})
# Basenames worth pointing the model at when a tree is too big to list whole.
MANIFEST_NAMES = frozenset({
    "package.json", "pyproject.toml", "requirements.txt", "pipfile", "go.mod",
    "go.work", "cargo.toml", "gemfile", "pom.xml", "build.gradle",
    "build.gradle.kts", "composer.json", "mix.exs", "package.swift",
    "pubspec.yaml", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "compose.yml", "compose.yaml", "readme.md", ".env.example", ".env.sample",
    ".env.template", "serverless.yml", "main.tf", "variables.tf", "chart.yaml",
    "values.yaml", "procfile", "makefile", "pnpm-workspace.yaml", "turbo.json",
    "nx.json", "lerna.json", "codeowners",
})
MANIFEST_SUFFIXES = (".csproj", ".fsproj", ".tf", ".sln")
MAX_LISTING_ENTRIES = 400


def is_noise(path: str) -> bool:
    return any(part in NOISE_DIRS for part in path.split("/")[:-1])


def looks_like_manifest(path: str) -> bool:
    base = path.rsplit("/", 1)[-1].lower()
    return base in MANIFEST_NAMES or base.endswith(MANIFEST_SUFFIXES)


class RepoToolbox:
    """Tools over one snapshot. ``scope`` narrows the default listing to one
    component's directory (a monorepo sub-tree) while ``read_file`` stays
    repository-wide, so a scoped run can still open root manifests.

    Scoped toolboxes made with ``scoped()`` share the tree cache and the
    ``files_read`` record with their parent, so evidence is counted once per
    inference run.
    """

    def __init__(self, snapshot: RepositorySnapshot, full_path: str, scope: str = "", *, _shared=None):
        self._snapshot = snapshot
        self._full_path = full_path
        self._scope = clean_path(scope)
        self._shared = _shared if _shared is not None else {"tree": None, "tree_size": None, "read": []}

    def scoped(self, path: str) -> "RepoToolbox":
        return RepoToolbox(self._snapshot, self._full_path, path, _shared=self._shared)

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def tree_size(self) -> int | None:  # None until list_repo_files ran
        return self._shared["tree_size"]

    @property
    def files_read(self) -> list[str]:
        return self._shared["read"]

    def _root_aliases(self) -> set[str]:
        # Models name the root as '', '.', '/', the repo's full path or its name.
        aliases = {"", ".", self._full_path.lower(), self._full_path.rsplit("/", 1)[-1].lower()}
        if self._scope:
            aliases.add(self._scope.lower())
        return aliases

    def load_tree(self) -> list[str]:
        if self._shared["tree"] is None:
            raw = self._snapshot.list_files() or []
            self._shared["tree_size"] = len(raw)
            self._shared["tree"] = [p for p in raw if not is_noise(p)]
        return self._shared["tree"]

    @tool
    def list_repo_files(
        self,
        path: Annotated[
            str,
            "Directory path relative to the repository root, e.g. 'src' or "
            "'infra/terraform'. Pass '' (or '.' or '/') to list the whole repository.",
        ] = "",
    ) -> str:
        """List the repository's files, one path per line.

        With no path (or '.', '/') lists the whole repository — or, when the
        analysis is scoped to one component, that component's directory; a
        large listing gets a directory summary plus every manifest/config
        file found anywhere. With a directory path lists only the files under
        it. Generated and dependency folders (node_modules, vendor, dist, …)
        are hidden.
        """
        tree = self.load_tree()
        if not tree:
            return "The repository listing is empty (no readable files on this branch)."

        p = clean_path(path)
        if p.lower() in self._root_aliases():
            if self._scope:
                return self._list_under(tree, self._scope, path)
            return self._list_root(tree)
        return self._list_under(tree, p, path)

    def _list_under(self, tree: list[str], p: str, as_written: str) -> str:
        prefix = p + "/"
        matches = [f for f in tree if f.startswith(prefix)]
        if not matches:
            top = sorted({f.split("/", 1)[0] for f in tree})
            return (
                f"No files under '{as_written}'. Top-level entries: {', '.join(top[:60])}. "
                "Pass '' to list the whole repository."
            )
        return self._render(matches, f"under '{p}'")

    def _list_root(self, tree: list[str]) -> str:
        if len(tree) <= MAX_LISTING_ENTRIES:
            return "\n".join(tree)
        counts: dict[str, int] = {}
        root_files = []
        for f in tree:
            if "/" in f:
                d = f.split("/", 1)[0]
                counts[d] = counts.get(d, 0) + 1
            else:
                root_files.append(f)
        lines = [f"{len(tree)} files. Root files:", *root_files, "", "Directories (file count):"]
        lines += [f"{d}/ ({n})" for d, n in sorted(counts.items())]
        manifests = [f for f in tree if "/" in f and looks_like_manifest(f)]
        if manifests:
            lines += ["", "Manifest/config files in subdirectories:", *manifests[:150]]
        lines += ["", "Call list_repo_files(path='<directory>') to see the files in one directory."]
        return "\n".join(lines)

    @staticmethod
    def _render(paths: list[str], where: str) -> str:
        shown = paths[:MAX_LISTING_ENTRIES]
        out = "\n".join(shown)
        if len(paths) > len(shown):
            out += (
                f"\n… {len(paths) - len(shown)} more files {where}; "
                "pass a deeper directory path to see them."
            )
        return out

    @tool
    def read_file(
        self,
        path: Annotated[
            str, "File path relative to the repository root, exactly as list_repo_files shows it"
        ],
    ) -> str:
        """Read a text file and return its contents.

        Returns a '[no readable file at …]' message when the path does not exist
        or is not a text file — check list_repo_files for the exact path.
        """
        p = clean_path(path)
        content = self._snapshot.read_file(p)
        if content is None and self._scope and not p.startswith(self._scope + "/"):
            # A scoped model often writes paths relative to its component.
            content = self._snapshot.read_file(f"{self._scope}/{p}")
            if content is not None:
                p = f"{self._scope}/{p}"
        if content is None:
            return (
                f"[no readable file at '{path}' — it is missing or binary. "
                "Use list_repo_files to find the exact path.]"
            )
        self._shared["read"].append(p)
        return content if content else f"[file '{p}' exists but is empty]"
