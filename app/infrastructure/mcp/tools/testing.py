from app.application.project_service import SandboxService
from app.infrastructure.mcp.registry import register

_service = SandboxService()


@register
def run_policy_test(policy_code: str, mock_input: dict | None = None) -> dict:
    """Run policy code against mock project data in the sandbox.

    Executes the evaluate(project) function in an isolated gVisor container
    and returns the result without saving anything.

    Args:
        policy_code: Python source code with an evaluate(project) function.
        mock_input: Optional mock project data. Supported keys:
            - files: list of {"path": str, "content": str} dicts
            - languages: dict of {"LanguageName": percentage_float}
            - members: list of {"username": str, "role": str}
            - contributors: list of {"username": str, "commits": int}
            - default_branch: str
            - topics: list of str
            - metadata: dict with name, description, web_url

    Returns:
        {passed: bool, score: int, message: str, details: dict}
    """
    return _service.run_policy_test(policy_code, mock_input or {})
