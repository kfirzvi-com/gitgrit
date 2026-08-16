from mcp.server.fastmcp.prompts.base import UserMessage

from app.infrastructure.mcp.registry import register_prompt


@register_prompt
def write_standard_from_requirement(
    requirement: str,
    language: str | None = None,
) -> list[UserMessage]:
    """Guide the AI assistant to write, test, and save a standard from a plain-language requirement.

    Args:
        requirement: What the standard should check (e.g. "every repo must have a CODEOWNERS file").
        language: Optional — restrict the standard to repos using this language (e.g. "python").
    """
    lang_step = (
        f"\n   - `languages=[{language!r}]` to target only {language} projects."
        if language
        else ""
    )
    return [
        UserMessage(
            f"Write a GitGrit compliance standard that checks: {requirement}.\n\n"
            "Follow these steps in order:\n\n"
            "1. Call `get_project_context_api()` to confirm which project methods are available.\n"
            "2. Call `list_projects()` to understand what repositories and languages exist — "
            "this helps you write realistic mock data.\n"
            "3. Write the `evaluate(project)` function:\n"
            "   - Return `{\"passed\": bool, \"score\": int, \"message\": str, \"details\": dict}`.\n"
            "   - Handle the case where `get_file_content()` returns `None`.\n"
            "   - Use intermediate scores to reflect partial compliance, not just 0 or 100.\n"
            "   - Keep the message to one sentence — it shows in the GitGrit UI.\n"
            "4. Call `run_standard_test()` with mock data covering at least two cases: one that "
            "passes and one that fails. Fix any exceptions or wrong results before continuing.\n"
            "5. Call `create_standard()` with:\n"
            "   - A clear, short name.\n"
            "   - The tested code.\n"
            "   - A description explaining what it checks and why.\n"
            "   - `events=[\"push\"]` unless the user specifies otherwise."
            f"{lang_step}\n"
            "   - `draft=False` unless the user wants to review before activating.\n"
            "6. Report the created standard ID and confirm whether it is active or draft."
        )
    ]


@register_prompt
def audit_workspace() -> list[UserMessage]:
    """Guide the AI assistant to perform a full compliance audit of the GitGrit workspace.

    Surveys all projects and standards, identifies coverage gaps, and proposes new standards.
    """
    return [
        UserMessage(
            "Perform a full compliance audit of this GitGrit workspace.\n\n"
            "## Step 1 — Inventory Projects\n"
            "Call `list_projects()` and summarise:\n"
            "- Total project count.\n"
            "- Breakdown by lifecycle stage (development / staging / production / etc.).\n"
            "- Primary languages in use.\n"
            "- Any projects with unusual configurations (no tags, no description, etc.).\n\n"
            "## Step 2 — Inventory Existing Standards\n"
            "Call `list_standards()` and summarise:\n"
            "- Total standard count, split by active vs draft.\n"
            "- Which events each standard triggers on.\n"
            "- Language/lifecycle filters in use.\n"
            "- Label categories present (security, ci, docs, ownership, etc.).\n\n"
            "## Step 3 — Identify Coverage Gaps\n"
            "Cross-reference projects against standards to find:\n"
            "- Lifecycle stages with no active standards (e.g. production repos with no checks).\n"
            "- Languages with no language-targeted standards.\n"
            "- Missing check categories:\n"
            "  * Documentation (README, CHANGELOG, contributing guide)\n"
            "  * Ownership (CODEOWNERS, defined maintainers)\n"
            "  * CI/CD (workflow files, test configuration)\n"
            "  * Security (dependency scanning config, branch protection hints)\n"
            "  * Repository hygiene (description set, default branch named 'main', topics tagged)\n\n"
            "## Step 4 — Propose New Standards\n"
            "For each significant gap, propose a standard with:\n"
            "- A name and one-sentence description.\n"
            "- Which projects it would target (language filter, lifecycle).\n"
            "- Which event(s) should trigger it.\n"
            "- A rough sketch of what `evaluate(project)` would check.\n\n"
            "Ask the user which proposals to implement. For each approved proposal, follow the "
            "`write_standard_from_requirement` workflow: `get_project_context_api` → write code → "
            "`run_standard_test` → `create_standard`."
        )
    ]
