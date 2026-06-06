"""Sandbox container entrypoint.

Reads /input.json for config (platform, project_id, access_token, and an
optional llm_roles map), creates the appropriate provider, wraps it in a
ProjectContext, loads /policy.py and calls evaluate(project) — or
evaluate(project, llm) for LLM policies — then writes the JSON result to stdout.

stdout is the result channel: the host parses it as a single JSON document.
Anything else written there (the policy's own prints, or LLM libraries like
litellm that emit banners/debug to stdout) would corrupt that channel, so we
redirect stdout to stderr for the duration of execution and emit only the
final JSON on the real stdout.
"""

import inspect
import json
import sys
import traceback

from project_context import ProjectContext
from providers.factory import create_provider


def _run(config):
    provider = create_provider(
        platform=config.get("platform", "mock"),
        project_id=config.get("project_id", ""),
        access_token=config.get("access_token"),
        base_url=config.get("base_url", ""),
        full_path=config.get("full_path", ""),
        mock_data=config.get("mock_data"),
    )
    project = ProjectContext(provider)

    # Only pull in the LLM stack (litellm) when the workspace has roles
    # configured — deterministic policies stay fast and dependency-free.
    llm = None
    policy_globals = {}
    if config.get("llm_roles"):
        from llm import LLM, PolicyVerdict

        llm = LLM(config["llm_roles"], project)
        policy_globals["PolicyVerdict"] = PolicyVerdict

    with open("/policy.py") as f:
        exec(f.read(), policy_globals)

    evaluate = policy_globals.get("evaluate")
    if evaluate is None:
        raise RuntimeError("Policy does not define an evaluate() function")

    # evaluate(project) is deterministic; evaluate(project, llm) is an LLM policy.
    if len(inspect.signature(evaluate).parameters) >= 2:
        if llm is None:
            raise RuntimeError(
                "This policy requires an LLM, but no LLM role is configured "
                "for this workspace. Configure one under Workspace Settings → LLM."
            )
        result = evaluate(project, llm)
    else:
        result = evaluate(project)

    # Surface token usage for visibility (foundation for future budgets).
    if llm is not None and isinstance(result, dict):
        details = result.setdefault("details", {})
        if isinstance(details, dict):
            details["llm_usage"] = llm.usage

    return result


def main():
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # keep policy/LLM chatter off the result channel
    try:
        with open("/input.json") as f:
            config = json.load(f)
        result = _run(config)
    except Exception:
        result = {
            "passed": False,
            "score": 0,
            "message": f"Policy execution error: {traceback.format_exc()}",
            "details": {"error": True},
        }
    finally:
        sys.stdout = real_stdout

    print(json.dumps(result))


if __name__ == "__main__":
    main()
