"""Sandbox container entrypoint.

Reads /input.json for config (platform, project_id, access_token, and an
optional llm_roles map), creates the appropriate provider, wraps it in a
ProjectContext, loads /policy.py and calls evaluate(...), then writes the JSON
result to stdout.

Policy signature is resolved by parameter name: the first parameter is always
the project; a parameter named ``llm`` receives the LLM object, and one named
``log`` receives the run's PolicyLogger. So all of these are valid:
    evaluate(project)
    evaluate(project, llm)
    evaluate(project, log)
    evaluate(project, llm, log)

stdout is the result channel: the host parses it as a single JSON document.
Anything else written there (policy prints, or LLM libraries like litellm that
emit banners to stdout) would corrupt that channel, so we redirect stdout to
stderr during execution and emit only the final JSON on the real stdout. The
captured log is attached to the result as ``logs`` (even on error).
"""

import inspect
import json
import sys
import traceback

from policy_log import PolicyLogger
from project_context import ProjectContext
from providers.factory import create_provider


def _run(config, logger):
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

        llm = LLM(config["llm_roles"], project, logger=logger)
        policy_globals["PolicyVerdict"] = PolicyVerdict

    with open("/policy.py") as f:
        exec(f.read(), policy_globals)

    evaluate = policy_globals.get("evaluate")
    if evaluate is None:
        raise RuntimeError("Policy does not define an evaluate() function")

    # First parameter is the project; inject llm/log by parameter name.
    params = list(inspect.signature(evaluate).parameters)
    kwargs = {}
    for name in params[1:]:
        if name == "llm":
            if llm is None:
                raise RuntimeError(
                    "This policy requires an LLM, but no LLM role is configured "
                    "for this workspace. Configure one under "
                    "Workspace Settings → LLM."
                )
            kwargs["llm"] = llm
        elif name == "log":
            kwargs["log"] = logger

    result = evaluate(project, **kwargs)

    # Surface token usage for visibility (foundation for future budgets).
    if llm is not None and isinstance(result, dict):
        details = result.setdefault("details", {})
        if isinstance(details, dict):
            details["llm_usage"] = llm.usage

    return result


def main():
    logger = PolicyLogger()
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # keep policy/LLM chatter off the result channel
    try:
        with open("/input.json") as f:
            config = json.load(f)
        result = _run(config, logger)
    except Exception:
        logger.error("policy execution raised an exception")
        result = {
            "passed": False,
            "score": 0,
            "message": f"Policy execution error: {traceback.format_exc()}",
            "details": {"error": True},
        }
    finally:
        sys.stdout = real_stdout

    if isinstance(result, dict):
        result.setdefault("logs", logger.entries)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
