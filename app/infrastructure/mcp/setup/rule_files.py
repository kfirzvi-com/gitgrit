"""Editor rule-file generators for non-Claude MCP clients.

Each function returns the file contents for a particular editor's rules
convention. The same operational guidance appears in every file: how to
bootstrap the project once, and how to call ``validate_edit`` before any
proposed file change. Output is plain text — callers (an MCP tool or an
HTTP endpoint) decide how to deliver it.
"""

from typing import Literal

Client = Literal["cursor", "cline"]

_BODY = """\
# GitGrit policy enforcement

GitGrit is a DevOps compliance platform connected to this project via MCP. The MCP \
server exposes tools that let the assistant resolve the project, fetch active policies, \
and validate file edits against forbidden-pattern rules.

You operate without a Claude plugin: there is no SessionStart hook to bootstrap the \
project for you. Follow the steps below explicitly.

## On first use in this project

1. Get the git remote URL or org/repo path (e.g. run `git remote get-url origin`).
2. Call the MCP tool `session_bootstrap(repo_full_path=..., web_url=...)`. The result has \
three keys: `project`, `status`, `policies`.
3. Branch on the result and tell the developer in one sentence:
   - `project.error == "no_match"` → this repo isn't a GitGrit project; enforcement is \
OFF for this session. Suggest the closest matches in `project.candidates`.
   - `policies == []` → the project resolved but no active policies are linked; \
enforcement is OFF for this session.
   - Otherwise → enforcement is ON; remember the `project.id` for the rest of the \
session.

## Before any tool that takes `project_id`

If you don't have a `project_id` yet, call `session_bootstrap` first.

## Before every proposed file edit

1. Call `validate_edit(project_id=<id>, file_path=<path>, prior_content=<current file \
content>, new_content=<proposed content>)`. For new files, pass `prior_content=null`.
2. Block on `introduced_violations`: name the policy, quote the matched substring, \
propose a fix, and wait for developer confirmation. If the developer says proceed \
anyway, proceed — the developer has final say.
3. Treat `pre_existing_violations_count` as informational only — do not try to fix \
those unless the developer asks.
4. Read `notes` for soft warnings (e.g. the extractor couldn't fully parse a rule; \
the server-side sandbox is authoritative on the next webhook event).

## Hard rule — no invented enforcement

Only enforce a rule if its exact `{kind, value}` was returned by `validate_edit` for \
the current project. Filenames, READMEs, language idioms, and your general knowledge \
are not sources of GitGrit rules. When in doubt, say "no GitGrit policy covers this" \
and continue.
"""


def to_cursor_mdc() -> str:
    """Return Cursor MDC-format content for ``.cursor/rules/gitgrit.mdc``.

    `alwaysApply: true` means Cursor injects this block into every chat in this
    workspace. The empty `globs:` keeps it project-wide.
    """
    return (
        "---\n"
        "description: GitGrit DevOps compliance enforcement\n"
        "globs:\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"{_BODY}"
    )


def to_clinerules() -> str:
    """Return plain-markdown content for ``.clinerules/gitgrit.md``."""
    return _BODY


_TARGET_PATHS: dict[Client, str] = {
    "cursor": ".cursor/rules/gitgrit.mdc",
    "cline": ".clinerules/gitgrit.md",
}


def render(client: Client) -> tuple[str, str]:
    """Return (target_path, content) for a supported client."""
    if client == "cursor":
        return _TARGET_PATHS["cursor"], to_cursor_mdc()
    if client == "cline":
        return _TARGET_PATHS["cline"], to_clinerules()
    raise ValueError(f"Unsupported client: {client!r}")
